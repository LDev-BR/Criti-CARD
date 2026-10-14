"""Retry unreferenced account images after the database transaction commits."""
from pathlib import Path

import click
from flask import current_app
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from criticard.db import get_db
from criticard.models import Card, User, Work
from criticard.communities.models import Community
from criticard.storage import KINDS, LocalStorage, storage_backend_for_folder, valid_image_name
from .models import PendingImageDeletion


def image_is_referenced(kind, filename):
    db = get_db()
    config = current_app.config
    same_folder = Path(config['UPLOAD_FOLDER']).resolve() == Path(config['CAPA_FOLDER']).resolve()
    fields = []
    if kind == 'avatar' or same_folder:
        fields.append(User.imagem)
    if kind == 'cover' or same_folder:
        fields.extend((Card.capa, Work.capa, Community.cover))
    aliases = [filename]
    if kind == 'avatar' or same_folder:
        aliases.append('uploads/' + filename)
    if kind == 'cover' or same_folder:
        aliases.append('cards/' + filename)
        aliases.extend(('catalog-static:' + filename, 'catalog-static:cards/' + filename))
    # Catalog history may store its static-relative path instead of a basename.
    # A shared physical directory also requires checking the other image kind.
    return any(db.execute(select(field).where(field.in_(aliases)).limit(1)).fetchone() for field in fields)


def queue_image(kind, filename):
    if valid_image_name(filename) and not image_is_referenced(kind, filename):
        db = get_db()
        create = sqlite_insert if db.dialect == 'sqlite' else postgres_insert
        db.execute(create(PendingImageDeletion).values(kind=kind, filename=filename)
            .on_conflict_do_nothing(index_elements=[PendingImageDeletion.kind, PendingImageDeletion.filename]))


def cleanup_images(limit=100):
    db = get_db()
    tasks = db.execute(select(PendingImageDeletion).order_by(PendingImageDeletion.id).limit(limit)).fetchall()
    removed = failed = 0
    for task in tasks:
        try:
            if not image_is_referenced(task['kind'], task['filename']):
                folder = current_app.config[KINDS[task['kind']][0]]
                # The same filename may have a migrated local copy and an S3
                # object. Remove both; missing files/objects are idempotent.
                backend = storage_backend_for_folder(folder)
                backend.remove(task['filename'])
                if not isinstance(backend, LocalStorage):
                    LocalStorage(folder).remove(task['filename'])
            with db:
                db.execute(delete(PendingImageDeletion).where(PendingImageDeletion.id == task['id']))
            removed += 1
        except Exception:
            # Storage failure cannot undo a committed account deletion. Leave
            # the filename in the queue, without account/text/IP or raw errors.
            db.rollback()
            current_app.logger.warning('Remoção de imagem pendente; execute privacy-cleanup-images para repetir.')
            failed += 1
    return {'processed': removed, 'failed': failed}


def init_app(app):
    @app.cli.command('privacy-cleanup-images')
    @click.option('--limit', type=click.IntRange(1, 1000), default=100, show_default=True)
    def cleanup_command(limit):
        report = cleanup_images(limit)
        click.echo(f"Imagens processadas: {report['processed']}; pendentes por falha: {report['failed']}.")
        if report['failed']:
            raise click.ClickException('Falha no armazenamento; a fila foi preservada para nova tentativa.')
