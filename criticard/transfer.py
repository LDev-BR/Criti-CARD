"""Verified, atomic SQLite imports into an explicitly empty PostgreSQL target."""
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory

import click
from flask import Flask
from sqlalchemy import DateTime, Integer, MetaData, delete, func, insert, select, text
from sqlalchemy.exc import SQLAlchemyError

from .config import ROOT
from . import db


class TransferError(ValueError):
    pass


@contextmanager
def prepared_sqlite_source(source):
    """Back up a readonly source and upgrade the isolated copy, never the source."""
    try:
        source_path = Path(source).expanduser().resolve(strict=True)
    except (OSError, RuntimeError):
        raise TransferError('O arquivo SQLite de origem não foi encontrado.') from None
    if not source_path.is_file():
        raise TransferError('A origem deve ser um arquivo SQLite.')
    with TemporaryDirectory(prefix='criticard-import-') as folder:
        isolated = Path(folder).resolve()
        snapshot = isolated / 'source-copy.db'
        engine = None
        try:
            with closing(sqlite3.connect(source_path.as_uri() + '?mode=ro', uri=True)) as original:
                with closing(sqlite3.connect(snapshot)) as backup:
                    original.backup(backup)
            # A minimal app avoids environment/secret loading and shared Socket.IO
            # initialization. Only the explicit migration command is needed here.
            app = Flask('criticard-import-copy', instance_path=str(isolated))
            app.config.update(DATABASE=str(snapshot), DATABASE_URL=None,
                SECRET_KEY='isolated-copy-never-serves-requests', TESTING=True)
            db.init_app(app)
            engine = app.extensions['database_engine']
            db.upgrade_database(app)
            with engine.connect() as connection:
                if connection.execute(text('PRAGMA foreign_key_check')).first() is not None:
                    raise TransferError('A origem contém relacionamentos inválidos; nada foi importado.')
            yield engine
        except TransferError:
            raise
        except (sqlite3.Error, SQLAlchemyError, ValueError, OSError):
            raise TransferError('Não foi possível preparar a cópia SQLite. A origem foi preservada.') from None
        finally:
            if engine is not None:
                engine.dispose()


def _metadata(connection):
    metadata = MetaData()
    metadata.reflect(bind=connection)
    return metadata


def _tables(metadata):
    return [table for table in metadata.sorted_tables if table.name != 'alembic_version']


def _seed():
    # The baseline's frozen seed is the only catalog we may replace. Never infer
    # "empty" from the absence of users when custom catalog data is present.
    spec = spec_from_file_location('criticard_frozen_core_seed', ROOT / 'migrations' / 'versions' / '0001_core.py')
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.SEED


def _assert_initial_community_seed(connection, metadata, category_slugs):
    communities = connection.execute(select(metadata.tables['communities'])).mappings().all()
    if not communities:
        return
    # Frozen 0015_thematic_communities defaults, tied to the frozen 0001 catalog.
    # A seeded flag alone does not identify untouched application bootstrap data.
    styles = {'jogos': ('violet', 'game'), 'filmes': ('rose', 'film'),
        'series': ('blue', 'film'), 'livros': ('green', 'book'),
        'animes': ('gold', 'film'), 'mangas': ('dark', 'book')}
    fields = ('slug', 'name', 'description', 'theme', 'icon', 'cover', 'mode',
        'minimum_level', 'created_by', 'seeded', 'archived')
    expected = {(slug, 'tema-' + slug, name[:80],
        f'Comunidade temática de {name} para críticas e conversas.',
        *styles[slug], None, 'open', 1, None, 1, 0) for slug, name, _ in _seed()}
    actual = {(category_slugs.get(row['category_id']),
        *(row[field] for field in fields)) for row in communities}
    # The migration uses one instant for every row, with no subsequent edits.
    valid = len(communities) == len(expected) and actual == expected \
        and len({row['created_at'] for row in communities}) == 1 \
        and all(row['created_at'] is not None and row['created_at'] == row['updated_at']
            for row in communities)
    if not valid:
        raise TransferError('As comunidades do destino foram alteradas. A importação foi recusada.')


def _assert_empty_target(connection, metadata):
    for table in _tables(metadata):
        if table.name not in ('categorias', 'obras', 'communities') and connection.execute(
                select(func.count()).select_from(table)).scalar():
            raise TransferError('O destino contém dados de aplicação. A importação foi recusada.')
    categories = metadata.tables['categorias']
    works = metadata.tables['obras']
    actual_categories = connection.execute(select(categories)).mappings().all()
    actual_works = connection.execute(select(works)).mappings().all()
    slugs = {row['id']: row['slug'] for row in actual_categories}
    _assert_initial_community_seed(connection, metadata, slugs)
    if not actual_categories and not actual_works:
        return
    expected_categories = {(slug, name) for slug, name, _ in _seed()}
    expected_works = {(slug, title) for slug, _, titles in _seed() for title in titles}
    valid = len(actual_categories) == len(expected_categories) \
        and {(row['slug'], row['nome']) for row in actual_categories} == expected_categories \
        and len(actual_works) == len(expected_works) \
        and {(slugs.get(row['categoria_id']), row['titulo']) for row in actual_works} == expected_works \
        and all(row['capa'] is None and row['search_title'] == row['titulo'].casefold()
            and row['active'] == 1 and row['created_at'] is None for row in actual_works)
    if not valid:
        raise TransferError('O catálogo do destino foi alterado. A importação foi recusada.')


def _compatible(source, target, source_connection, target_connection):
    source_tables = {table.name: table for table in _tables(source)}
    target_tables = {table.name: table for table in _tables(target)}
    if set(source_tables) != set(target_tables) or any(
            set(table.columns.keys()) != set(target_tables[name].columns.keys())
            for name, table in source_tables.items()):
        raise TransferError('Origem e destino precisam ter o esquema completo das mesmas migrações.')
    for metadata, connection in ((source, source_connection), (target, target_connection)):
        if 'alembic_version' not in metadata.tables:
            raise TransferError('Execute db-upgrade no destino antes da importação.')
    source_versions = set(source_connection.execute(select(source.tables['alembic_version'].c.version_num)).scalars())
    target_versions = set(target_connection.execute(select(target.tables['alembic_version'].c.version_num)).scalars())
    if source_versions != target_versions:
        raise TransferError('Execute db-upgrade no destino antes da importação.')


def _typed_row(row, target):
    result = dict(row)
    for column in target.columns:
        value = result[column.name]
        if value is not None and isinstance(column.type, DateTime):
            if isinstance(value, str):
                value = datetime.fromisoformat(value)
            if column.type.timezone and value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            result[column.name] = value
    return result


def _restart_sequences(connection, tables):
    preparer = connection.dialect.identifier_preparer
    for table in tables:
        for column in table.primary_key.columns:
            if not isinstance(column.type, Integer):
                continue
            sequence = connection.execute(text('''
                SELECT ns.nspname, seq.relname FROM pg_class seq
                JOIN pg_namespace ns ON ns.oid=seq.relnamespace
                WHERE seq.oid=CAST(pg_get_serial_sequence(:table_name,:column_name) AS regclass)
            '''), {'table_name': preparer.format_table(table), 'column_name': column.name}).first()
            if sequence is None:
                continue
            maximum = connection.execute(select(func.max(column))).scalar()
            next_id = (maximum or 0) + 1
            sequence_name = preparer.quote_schema(sequence[0]) + '.' + preparer.quote(sequence[1])
            # ALTER RESTART participates in the import transaction, including a
            # dry-run rollback; setval() would change sequence state independently.
            connection.execute(text(f'ALTER SEQUENCE {sequence_name} RESTART WITH {next_id}'))


def import_sqlite(source, *, confirm_empty_target=False, dry_run=False):
    if not confirm_empty_target:
        raise TransferError('Use --confirm-empty-target para confirmar o destino vazio.')
    target_engine = db.get_engine()
    if target_engine.dialect.name != 'postgresql':
        raise TransferError('O destino precisa ser PostgreSQL, migrado e sem dados de aplicação.')
    try:
        with prepared_sqlite_source(source) as source_engine, source_engine.connect() as origin:
            source_metadata = _metadata(origin)
            with target_engine.connect() as target, target.begin() as transaction:
                target_metadata = _metadata(target)
                _compatible(source_metadata, target_metadata, origin, target)
                target_tables = _tables(target_metadata)
                names = ', '.join(target.dialect.identifier_preparer.format_table(table) for table in target_tables)
                # Exclude a race with concurrent writes between validation and copy.
                target.execute(text('LOCK TABLE ' + names + ' IN ACCESS EXCLUSIVE MODE'))
                _assert_empty_target(target, target_metadata)
                target.execute(delete(target_metadata.tables['communities']))
                target.execute(delete(target_metadata.tables['obras']))
                target.execute(delete(target_metadata.tables['categorias']))
                counts = {}
                for source_table in _tables(source_metadata):
                    destination = target_metadata.tables[source_table.name]
                    count = 0
                    for rows in origin.execute(select(source_table)).mappings().partitions(500):
                        target.execute(insert(destination), [_typed_row(row, destination) for row in rows])
                        count += len(rows)
                    counts[source_table.name] = count
                for table in target_tables:
                    if target.execute(select(func.count()).select_from(table)).scalar() != counts[table.name]:
                        raise TransferError('A conferência das contagens falhou; a importação foi revertida.')
                # Immediate FKs already checked each INSERT. Validate deferred ones
                # before reporting success and before sequence restart/commit.
                target.execute(text('SET CONSTRAINTS ALL IMMEDIATE'))
                _restart_sequences(target, target_tables)
                if dry_run:
                    transaction.rollback()
        return {'dry_run': dry_run, 'counts': counts}
    except TransferError:
        raise
    except (SQLAlchemyError, ValueError, TypeError, OverflowError):
        # Do not expose SQL parameters (password hashes, email or message bodies).
        raise TransferError('A importação falhou e foi revertida. Origem e dados do destino foram preservados.') from None


def init_app(app):
    @app.cli.command('db-import-sqlite')
    @click.argument('source', type=click.Path(exists=True, dir_okay=False, path_type=Path))
    @click.option('--confirm-empty-target', is_flag=True, help='Confirma que o destino PostgreSQL está vazio.')
    @click.option('--dry-run', is_flag=True, help='Valida toda a importação e reverte a transação no final.')
    def import_command(source, confirm_empty_target, dry_run):
        try:
            report = import_sqlite(source, confirm_empty_target=confirm_empty_target, dry_run=dry_run)
        except TransferError as error:
            raise click.ClickException(str(error)) from None
        click.echo('Validação concluída; destino preservado.' if dry_run else 'Importação concluída e conferida.')
        for table, count in sorted(report['counts'].items()):
            click.echo(f'{table}: {count}')
