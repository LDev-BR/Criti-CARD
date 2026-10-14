"""Socket events authenticate independently and never disclose private history."""
from uuid import uuid4

from sqlalchemy import delete, update
from werkzeug.security import generate_password_hash

from criticard.db import get_db
from criticard.models import User
from test_chat import app, member, send, start, action


def connection(app, user_id, origin=None):
    from criticard.chat import socketio
    client, token = member(app, user_id)
    socket = socketio.test_client(app, namespace='/chat', flask_test_client=client,
        auth={'csrf_token': token}, headers={'Origin': origin or 'http://localhost'})
    return socket, client, token


def test_socket_connect_requires_session_csrf_and_same_origin(app):
    from criticard.chat import socketio
    anonymous = app.test_client()
    rejected = socketio.test_client(app, namespace='/chat', flask_test_client=anonymous, auth={})
    assert not rejected.is_connected('/chat')
    client, token = member(app, 1)
    for auth, origin in [({'csrf_token': 'bad'}, 'http://localhost'), ({}, 'http://localhost'),
                         ({'csrf_token': token}, 'https://attacker.example')]:
        rejected = socketio.test_client(app, namespace='/chat', flask_test_client=client,
            auth=auth, headers={'Origin': origin})
        assert not rejected.is_connected('/chat')
    allowed, _, _ = connection(app, 1)
    assert allowed.is_connected('/chat')
    allowed.disconnect(namespace='/chat')


def test_socket_membership_and_delivery_are_private_and_persisted(app):
    client, token, conversation = start(app)
    alice, _, _ = connection(app, 1)
    bob, _, _ = connection(app, 2)
    third, _, _ = connection(app, 3)
    assert third.emit('join', {'conversation_id': conversation}, namespace='/chat', callback=True)['code'] == 404
    for socket in [alice, bob]:
        assert socket.emit('join', {'conversation_id': conversation}, namespace='/chat', callback=True)['ok']
        socket.get_received('/chat')
    nonce = str(uuid4())
    ack = alice.emit('send_message', {'conversation_id': conversation, 'body': 'Privada', 'client_nonce': nonce},
        namespace='/chat', callback=True)
    assert ack['ok'] and ack['created']
    history = client.get(f'/mensagens/{conversation}/historico').json
    assert history['messages'][0]['id'] == ack['message']['id']
    assert bob.get_received('/chat')[0]['args']['message']['body'] == 'Privada'
    assert third.get_received('/chat') == []
    assert 'email' not in str(ack) and 'senha' not in str(ack)
    retry = alice.emit('send_message', {'conversation_id': conversation, 'body': 'Retry', 'client_nonce': nonce},
        namespace='/chat', callback=True)
    assert retry['ok'] and not retry['created']
    assert bob.get_received('/chat') == []
    for socket in [alice, bob, third]:
        socket.disconnect(namespace='/chat')


def test_socket_reconnect_recovers_missing_messages_and_scopes_read(app):
    client, token, conversation = start(app)
    first = send(client, token, conversation, 'Primeira').json['message']['id']
    second = send(client, token, conversation, 'Segunda').json['message']['id']
    bob, _, _ = connection(app, 2)
    recovered = bob.emit('join', {'conversation_id': conversation, 'after_id': first},
        namespace='/chat', callback=True)
    assert [message['body'] for message in recovered['messages']] == ['Segunda']
    receipt = bob.emit('mark_read', {'conversation_id': conversation, 'message_id': second},
        namespace='/chat', callback=True)
    assert receipt['conversation']['unread_count'] == 0
    bob.disconnect(namespace='/chat')


def test_socket_logout_revokes_already_connected_session(app):
    client, token, conversation = start(app)
    alice, http, csrf = connection(app, 1)
    action(http, csrf, '/logout')
    result = alice.emit('send_message', {'conversation_id': conversation,
        'body': 'Revogada', 'client_nonce': str(uuid4())}, namespace='/chat', callback=True)
    assert not alice.is_connected('/chat')
    assert client.get(f'/mensagens/{conversation}/historico', headers={'Accept': 'application/json'}).status_code == 401


def test_deleted_and_inactive_accounts_cannot_use_existing_socket(app):
    _, _, conversation = start(app)
    alice, _, _ = connection(app, 1)
    with app.app_context():
        db = get_db()
        with db:
            db.execute(update(User).where(User.id == 1).values(active=0))
    alice.emit('join', {'conversation_id': conversation}, namespace='/chat', callback=True)
    assert not alice.is_connected('/chat')
    bob, _, _ = connection(app, 2)
    with app.app_context():
        db = get_db()
        with db:
            db.execute(delete(User).where(User.id == 2))
    bob.emit('join', {'conversation_id': conversation}, namespace='/chat', callback=True)
    assert not bob.is_connected('/chat')


def test_socket_rate_limit_and_dynamic_block_apply_to_events_and_delivery(app):
    from criticard.social.models import Block
    from sqlalchemy import insert
    app.config['CHAT_RATE_LIMIT'] = 1
    _, _, conversation = start(app)
    alice, _, _ = connection(app, 1)
    bob, _, _ = connection(app, 2)
    bob.emit('join', {'conversation_id': conversation}, namespace='/chat', callback=True)
    def emit(body):
        return alice.emit('send_message', {'conversation_id': conversation,
            'body': body, 'client_nonce': str(uuid4())}, namespace='/chat', callback=True)
    assert emit('Primeira')['ok']
    assert emit('Excessiva')['code'] == 429
    bob.get_received('/chat')
    with app.app_context():
        db = get_db()
        with db:
            db.execute(insert(Block).values(user_id=2, target_id=1))
    assert emit('Bloqueada')['code'] == 403
    assert bob.emit('join', {'conversation_id': conversation}, namespace='/chat', callback=True)['code'] == 403
    assert bob.get_received('/chat') == []
    alice.disconnect(namespace='/chat')
    bob.disconnect(namespace='/chat')


def test_join_delivers_message_created_between_history_snapshot_and_subscription(app, monkeypatch):
    from criticard.chat import service
    from criticard.chat.sockets import publish_message
    _, _, conversation = start(app)
    alice, _, _ = connection(app, 1)
    original_history = service.history
    def concurrent_history(*args, **kwargs):
        page = original_history(*args, **kwargs)
        message, _ = service.send_message(2, conversation, 'No intervalo da reconexão', str(uuid4()))
        publish_message(message)
        return page
    monkeypatch.setattr(service, 'history', concurrent_history)
    ack = alice.emit('join', {'conversation_id': conversation}, namespace='/chat', callback=True)
    assert ack['ok']
    received = alice.get_received('/chat')
    assert len(received) == 1
    assert received[0]['args']['message']['body'] == 'No intervalo da reconexão'
    alice.disconnect(namespace='/chat')


def test_socket_does_not_authenticate_replacement_account_with_reused_user_id(app):
    from sqlalchemy import insert
    _, _, conversation = start(app)
    alice, http, token = connection(app, 1)
    with app.app_context():
        db = get_db()
        with db:
            db.execute(delete(User).where(User.id == 1))
            db.execute(insert(User).values(id=1, username='NEWPERSON', nome='Nova pessoa',
                apelido='Leitor', about='Nova conta', email='new@example.com',
                senha=generate_password_hash('Different1!'), active=1, session_version=0))
    alice.emit('join', {'conversation_id': conversation}, namespace='/chat', callback=True)
    assert not alice.is_connected('/chat')
