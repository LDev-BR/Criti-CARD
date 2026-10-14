"""Opt-in privacy lifecycle and send/delete ordering on real PostgreSQL."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event, current_thread
from uuid import uuid4

import pytest
from sqlalchemy import event, select

from criticard.chat.service import ChatError, send_message, start_conversation
from criticard.chat.models import Message
from criticard.db import delete_user, get_db
from criticard.privacy.models import PrivacyReply, PrivacyRequest
from test_postgres import pg_app, pg_database_url, in_app
from test_privacy import create_request, member


def test_postgres_private_request_export_reply_and_account_erasure(pg_app):
    client, token = member(pg_app)
    protocol = create_request(client, token, body='Pedido isolado PostgreSQL').json['request']['protocol']
    outsider, _ = member(pg_app, 2)
    assert outsider.get('/privacidade/pedidos/' + protocol, headers={'Accept': 'application/json'}).status_code == 404
    administrator, admin_token = member(pg_app, 3)
    assert administrator.post('/admin/privacidade/' + protocol,
        json={'status': 'answered', 'body': 'Providência informada'},
        headers={'X-CSRF-Token': admin_token}).status_code == 200
    data = client.get('/configuracoes/conta/exportar').json
    assert data['privacy_requests'][0]['replies'][0]['body'] == 'Providência informada'
    with pg_app.app_context():
        conversation = start_conversation(1, 2)[0]['id']
        send_message(1, conversation, 'Mensagem enviada pela conta', str(uuid4()))
        send_message(2, conversation, 'Mensagem do outro participante', str(uuid4()))
    cover = Path(pg_app.config['CAPA_FOLDER']) / 'isolated.png'
    cover.write_bytes(b'fixture image')
    assert client.post('/excluir_user', data={'csrf_token': token, 'senha': 'Password1!'}).status_code == 302
    with pg_app.app_context():
        db = get_db()
        assert db.execute(select(Message.body)).fetchall() == [{'body': 'Mensagem do outro participante'}]
        assert db.execute(select(PrivacyRequest.id)).fetchall() == []
        assert db.execute(select(PrivacyReply.id)).fetchall() == []
        assert not cover.exists()


def test_postgres_deletion_serializes_with_waiting_send_and_prevents_retained_sender_text(pg_app):
    with pg_app.app_context():
        conversation = start_conversation(1, 2)[0]['id']
    locked, attempted, release = Event(), Event(), Event()
    engine = pg_app.extensions['database_engine']
    def after_delete(connection, cursor, statement, parameters, context, executemany):
        if current_thread().name.startswith('privacy-delete') and statement.startswith('DELETE FROM messages'):
            locked.set()
            assert release.wait(timeout=10)
    def before_lock(connection, cursor, statement, parameters, context, executemany):
        if current_thread().name.startswith('privacy-send') and 'FOR UPDATE' in statement:
            attempted.set()
    def erase():
        return in_app(pg_app, lambda: delete_user(1))
    def send():
        with pg_app.app_context(), pytest.raises(ChatError) as error:
            send_message(1, conversation, 'Não pode ficar com sender NULL', str(uuid4()))
        return error.value.status
    event.listen(engine, 'after_cursor_execute', after_delete)
    event.listen(engine, 'before_cursor_execute', before_lock)
    try:
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix='privacy-delete') as erasers, \
             ThreadPoolExecutor(max_workers=1, thread_name_prefix='privacy-send') as senders:
            eraser = erasers.submit(erase)
            assert locked.wait(timeout=10)
            sender = senders.submit(send)
            try:
                assert attempted.wait(timeout=10)
            finally:
                release.set()
            eraser.result(timeout=10)
            assert sender.result(timeout=10) in (401, 403, 404)
        with pg_app.app_context():
            assert get_db().execute(select(Message.id)).fetchall() == []
    finally:
        release.set()
        event.remove(engine, 'after_cursor_execute', after_delete)
        event.remove(engine, 'before_cursor_execute', before_lock)
