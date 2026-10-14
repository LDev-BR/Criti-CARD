import re
import pytest
from concurrent.futures import ThreadPoolExecutor
from time import monotonic, sleep

from sqlalchemy import select, text

from criticard.accounts.service import InvalidAccountToken, consume_reset, request_password_reset
from criticard.db import get_db
from criticard.models import User
from test_postgres import pg_app, pg_database_url


@pytest.mark.parametrize('path,status', [('/feed?q=%00', 200), ('/catalogo?q=%00', 200),
    ('/perfil/ALICE%00', 404), ('/colecao/ALICE%00', 404)])
def test_public_lookup_rejects_invalid_text_without_database_error(pg_app, path, status):
    assert pg_app.test_client().get(path).status_code == status


def test_chat_user_lookup_rejects_invalid_text(pg_app):
    from test_chat import action, member
    client, token = member(pg_app, 1)
    assert action(client, token, '/mensagens/iniciar', {'target_username': 'BOB\0'}).status_code == 400


def test_two_reset_links_for_same_account_serialize_without_deadlock(pg_app, tmp_path):
    outbox = tmp_path / 'private-outbox'
    pg_app.config.update(ACCOUNT_MAIL_BACKEND='file', ACCOUNT_BASE_URL='http://localhost',
                        ACCOUNT_OUTBOX_PATH=str(outbox), ACCOUNT_MAIL_FROM='no-reply@criticard.test')
    with pg_app.app_context():
        assert request_password_reset('bob@example.com', '127.0.0.1') == 0
        assert request_password_reset('bob@example.com', '127.0.0.1') == 0
    tokens = [re.search(r'/redefinir-senha/([A-Za-z0-9_-]{43})', path.read_text(encoding='utf-8')).group(1)
              for path in sorted(outbox.glob('*.eml'))]
    assert len(tokens) == 2

    def consume(token):
        with pg_app.app_context():
            try:
                consume_reset(token, 'Different2!', 'Different2!')
                return 'changed'
            except InvalidAccountToken:
                return 'expired'

    engine = pg_app.extensions['database_engine']
    with engine.connect() as holder:
        holder.execute(select(User.id).where(User.id == 2).with_for_update()).fetchall()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(consume, token) for token in tokens]
            try:
                deadline = monotonic() + 10
                queued = False
                while monotonic() < deadline:
                    with engine.connect() as observer:
                        waiting = observer.execute(text("SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND wait_event_type='Lock'")).scalar()
                    if waiting >= 2:
                        queued = True
                        break
                    sleep(.02)
                assert queued, 'Both real PostgreSQL requests must wait for the held account lock'
            finally:
                holder.commit()
            results = [future.result(timeout=15) for future in futures]
    assert sorted(results) == ['changed', 'expired']
    with pg_app.app_context():
        assert get_db().execute(select(User.session_version).where(User.id == 2)).scalar() == 1
