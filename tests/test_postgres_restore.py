"""Restore a real PostgreSQL dump into a new, isolated database."""
import os
import re
import shutil
import subprocess
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg import sql
import pytest
from sqlalchemy import create_engine, select, text

from criticard.config import ROOT
from criticard.models import Base
from test_postgres import pg_app, pg_database_url


def binary(name):
    folder = Path(os.getenv('CRITICARD_PG_BIN') or ROOT / '.runtime/postgresql-portable/pgsql/bin')
    local = folder / (name + ('.exe' if os.name == 'nt' else ''))
    executable = str(local) if local.is_file() else shutil.which(name)
    if not executable:
        pytest.skip('Install pg_dump/pg_restore or configure CRITICARD_PG_BIN')
    return executable


def snapshot(connection):
    result = {table.name: [dict(row._mapping) for row in connection.execute(
        select(table).order_by(*table.primary_key.columns))] for table in Base.metadata.sorted_tables}
    result['alembic_version'] = connection.execute(text('SELECT version_num FROM alembic_version')).scalar()
    return result


def test_real_dump_restore_preserves_accounts_and_social_history(pg_app, tmp_path):
    from criticard.backlog.service import add_item
    from criticard.social.service import create_comment, set_follow, set_like
    from criticard.social.connections import change_friendship
    from criticard.chat.service import mark_read, send_message, start_conversation
    from criticard.settings.service import save_preferences
    with pg_app.app_context():
        save_preferences(1, 'aparencia', {'color_scheme': 'midnight', 'high_contrast': True})
        save_preferences(2, 'chat', {'chat_enter_send': False})
        add_item(1, {'obra_id': 1})
        set_like(2, 1, True)
        create_comment(2, 1, 'Um comentário para preservar.')
        set_follow(2, 1, True)
        change_friendship(1, 2, 'request')
        change_friendship(2, 1, 'accept')
        change_friendship(3, 1, 'request')
        conversation, _ = start_conversation(1, 2)
        message, _ = send_message(1, conversation['id'], 'Histórico persistente.', str(uuid4()))
        mark_read(2, conversation['id'], message['id'])
    source = pg_app.extensions['database_engine']
    url = source.url
    name = 'criticard_restore_test_' + uuid4().hex
    assert re.fullmatch(r'criticard_restore_test_[0-9a-f]{32}', name)
    dump = tmp_path / 'isolated.dump'
    environment = {**os.environ, 'PGHOST': url.host, 'PGPORT': str(url.port or 5432),
                   'PGUSER': url.username, 'PGPASSWORD': url.password or ''}
    with source.connect() as connection:
        expected = snapshot(connection)
    with psycopg.connect(host=url.host, port=url.port, user=url.username, password=url.password or '',
                         dbname='postgres', connect_timeout=5, autocommit=True) as admin:
        admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
        restored = None
        try:
            for command in ([binary('pg_dump'), '-Fc', '--no-owner', '--no-acl', '-f', str(dump), '-d', url.database],
                            [binary('pg_restore'), '--no-owner', '--no-acl', '--exit-on-error', '-d', name, str(dump)]):
                result = subprocess.run(command, env=environment, capture_output=True, text=True, timeout=60)
                assert result.returncode == 0, result.stderr
            restored = create_engine(url.set(database=name))
            with restored.connect() as connection:
                assert snapshot(connection) == expected
        finally:
            if restored is not None:
                restored.dispose()
            admin.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
