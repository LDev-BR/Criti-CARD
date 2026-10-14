"""Opt-in integration against a real PostgreSQL server and GUID databases."""
import os
import re
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from time import monotonic, sleep
from uuid import uuid4

import psycopg
from psycopg import sql
import pytest
from sqlalchemy import func, insert, select, text, update
from sqlalchemy.engine import make_url
from werkzeug.exceptions import NotFound
from werkzeug.security import generate_password_hash

from criticard import create_app
from criticard.db import get_db
from criticard.models import Card, User


@pytest.fixture
def pg_database_url():
    configured = os.getenv('CRITICARD_TEST_POSTGRES_URL')
    if not configured:
        pytest.skip('Set CRITICARD_TEST_POSTGRES_URL to opt into real PostgreSQL tests')
    base = make_url(configured)
    if base.get_backend_name() != 'postgresql':
        raise ValueError('The integration database server must be PostgreSQL')
    database = 'criticard_integration_test_' + uuid4().hex
    assert re.fullmatch(r'criticard_integration_test_[0-9a-f]{32}', database)
    with psycopg.connect(host=base.host, port=base.port, user=base.username,
            password=base.password or '', dbname=base.database or 'postgres', autocommit=True) as admin:
        admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(database)))
        try:
            yield base.set(drivername='postgresql+psycopg', database=database).render_as_string(hide_password=False)
        finally:
            # Only a name generated and validated by this fixture can be dropped.
            admin.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(database)))


@pytest.fixture
def pg_app(pg_database_url, tmp_path):
    app = create_app({'TESTING': True, 'SECRET_KEY': 'postgres-integration-isolated-key',
        'DATABASE_URL': pg_database_url, 'DATABASE': str(tmp_path / 'unused-local.db'),
        'UPLOAD_FOLDER': str(tmp_path / 'avatars'), 'CAPA_FOLDER': str(tmp_path / 'covers'),
        'ADM_USERNAME': '', 'ADM_SENHA': '', 'CHAT_RATE_LIMIT': 100})
    with app.app_context():
        db = get_db()
        with db:
            for user_id, name in [(1, 'ALICE'), (2, 'BOB'), (3, 'ADMIN')]:
                db.execute(insert(User).values(id=user_id, username=name, nome=name.title(),
                    apelido='Leitor', about='Bio', email=name.lower() + '@example.com',
                    senha=generate_password_hash('Password1!'), admin=int(user_id == 3)))
            db.execute(insert(Card).values(id=1, titulo='Card da Alice', capa='isolated.png',
                sobre='Crítica no banco de teste', nota=90, author_id=1))
            db.execute(text("SELECT setval(pg_get_serial_sequence('usuarios','id'),3,true)"))
            db.execute(text("SELECT setval(pg_get_serial_sequence('cards','id'),1,true)"))
    yield app
    app.extensions['database_engine'].dispose()


def in_app(app, function):
    with app.app_context():
        return function()


def test_real_postgres_backlog_unique_and_private(pg_app):
    from criticard.backlog.service import add_item, collection_items, get_owned_item
    from criticard.backlog.models import BacklogItem
    with ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(lambda _: in_app(pg_app, lambda: add_item(1, {'obra_id': 1})), range(5)))
    assert sum(created for _, created in results) == 1
    item_id = results[0][0]['id']
    with pg_app.app_context():
        assert get_db().dialect == 'postgresql'
        assert get_db().execute(select(func.count()).select_from(BacklogItem)).scalar() == 1
        assert collection_items(1, {'categoria': '', 'q': '', 'status': ''}, public_only=True) == []
        with pytest.raises(NotFound):
            get_owned_item(2, item_id)


def test_real_postgres_like_concurrency_creates_one_notification(pg_app):
    from criticard.social.service import set_like
    from criticard.social.models import CardLike, Notification
    with ThreadPoolExecutor(max_workers=5) as pool:
        list(pool.map(lambda _: in_app(pg_app, lambda: set_like(2, 1, True)), range(5)))
    with pg_app.app_context():
        db = get_db()
        assert db.execute(select(func.count()).select_from(CardLike)).scalar() == 1
        assert db.execute(select(func.count()).select_from(Notification).where(Notification.recipient_id == 1)).scalar() == 1


def test_real_postgres_chat_nonce_membership_receipts_and_reconnect(pg_app):
    from criticard.chat import service, socketio
    from criticard.chat.models import Message
    from test_chat import member
    with pg_app.app_context():
        conversation, _ = service.start_conversation(1, 2)
    nonce = str(uuid4())
    with ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(lambda _: in_app(pg_app, lambda: service.send_message(
            1, conversation['id'], 'Uma única mensagem PG', nonce)), range(5)))
    assert sum(created for _, created in results) == 1
    first_id = results[0][0]['id']
    with pg_app.app_context():
        second, _ = service.send_message(1, conversation['id'], 'Durante a desconexão', str(uuid4()))
        assert get_db().execute(select(func.count()).select_from(Message)).scalar() == 2
        with pytest.raises(service.ChatError) as third:
            service.history(3, conversation['id'])
        assert third.value.status == 404
    bob, token = member(pg_app, 2)
    connected = socketio.test_client(pg_app, namespace='/chat', flask_test_client=bob,
        auth={'csrf_token': token}, headers={'Origin': 'http://localhost'})
    recovered = connected.emit('join', {'conversation_id': conversation['id'], 'after_id': first_id},
        namespace='/chat', callback=True)
    assert [message['body'] for message in recovered['messages']] == ['Durante a desconexão']
    read = connected.emit('mark_read', {'conversation_id': conversation['id'], 'message_id': second['id']},
        namespace='/chat', callback=True)
    assert read['conversation']['unread_count'] == 0
    with pg_app.app_context():
        db = get_db()
        with db:
            db.execute(update(User).where(User.id == 2).values(session_version=User.session_version + 1))
    connected.emit('join', {'conversation_id': conversation['id']}, namespace='/chat', callback=True)
    assert not connected.is_connected('/chat')


def test_real_postgres_block_waits_for_chat_pair_locks_then_stops_new_send(pg_app):
    from criticard.chat import service
    from criticard.social.service import set_block
    with pg_app.app_context():
        conversation, _ = service.start_conversation(1, 2)
    locked, release = Event(), Event()
    original_limit = service._consume_send_limit
    def hold_inside_send(db, user_id):
        locked.set()
        assert release.wait(timeout=10)
        return original_limit(db, user_id)
    service._consume_send_limit = hold_inside_send
    def send_while_holding():
        return in_app(pg_app, lambda: service.send_message(1, conversation['id'], 'Antes do bloqueio', str(uuid4())))
    def block():
        return in_app(pg_app, lambda: set_block(2, 1, True))
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            holder = pool.submit(send_while_holding)
            assert locked.wait(timeout=10)
            blocker = pool.submit(block)
            deadline = monotonic() + 5
            waiting = False
            while monotonic() < deadline and not waiting:
                with pg_app.extensions['database_engine'].connect() as observer:
                    waiting = observer.execute(text("SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND wait_event_type='Lock'")).scalar() > 0
                if not waiting:
                    sleep(.02)
            assert waiting, 'The real blocking write must wait for the running chat transaction'
            release.set()
            assert holder.result(timeout=10)[1]
            blocker.result(timeout=10)
    finally:
        release.set()
        service._consume_send_limit = original_limit
    with pg_app.app_context():
        with pytest.raises(service.ChatError) as refused:
            service.send_message(1, conversation['id'], 'Bloqueada', str(uuid4()))
        assert refused.value.status == 403


def test_real_postgres_password_reset_revokes_a_live_socket_and_cookie(pg_app, tmp_path):
    from criticard.accounts.service import consume_reset, request_password_reset, InvalidAccountToken
    from criticard.chat import service, socketio
    from test_chat import member
    pg_app.config.update(ACCOUNT_MAIL_BACKEND='file', ACCOUNT_BASE_URL='http://localhost',
        ACCOUNT_OUTBOX_PATH=str(tmp_path / 'private-outbox'), ACCOUNT_MAIL_FROM='no-reply@criticard.test')
    bob, csrf = member(pg_app, 2)
    connected = socketio.test_client(pg_app, namespace='/chat', flask_test_client=bob,
        auth={'csrf_token': csrf}, headers={'Origin': 'http://localhost'})
    with pg_app.app_context():
        conversation, _ = service.start_conversation(1, 2)
        assert request_password_reset('bob@example.com', '127.0.0.1') == 0
        files = list((tmp_path / 'private-outbox').glob('*.eml'))
        assert len(files) == 1
        raw = re.search(r'/redefinir-senha/([A-Za-z0-9_-]{43})', files[0].read_text(encoding='utf-8')).group(1)
        assert consume_reset(raw, 'NewPassword2!', 'NewPassword2!') == 2
        with pytest.raises(InvalidAccountToken):
            consume_reset(raw, 'NewPassword2!', 'NewPassword2!')
    connected.emit('join', {'conversation_id': conversation['id']}, namespace='/chat', callback=True)
    assert not connected.is_connected('/chat')
    assert bob.get('/mensagens', headers={'Accept': 'application/json'}).status_code == 401
