"""Private chat contracts against a migrated, temporary database."""
import re
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from sqlalchemy import delete, insert, select, update
from werkzeug.security import generate_password_hash

from criticard import create_app
from criticard.db import get_db
from criticard.models import User
from criticard.security import session_identity


@pytest.fixture
def app(tmp_path):
    application = create_app({'TESTING': True, 'SECRET_KEY': 'chat-test-key',
        'DATABASE': str(tmp_path / 'chat.db'), 'UPLOAD_FOLDER': str(tmp_path / 'avatars'),
        'CAPA_FOLDER': str(tmp_path / 'covers'), 'CHAT_RATE_LIMIT': 30})
    with application.app_context():
        db = get_db()
        with db:
            for user_id, name in [(1, 'ALICE'), (2, 'BOB'), (3, 'ADMIN')]:
                db.execute(insert(User).values(id=user_id, username=name, nome=name.title(),
                    apelido='Leitor', about='Minha bio', email=name.lower() + '@example.com',
                    senha=generate_password_hash('Password1!'), admin=int(user_id == 3)))
    yield application
    application.extensions['database_engine'].dispose()


def member(app, user_id):
    client = app.test_client()
    page = client.get('/')
    token = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
    assert token, 'CSRF token must come from a rendered form'
    with app.app_context():
        user = get_db().execute(select(User).where(User.id == user_id)).fetchone()
        identity = session_identity(user)
    with client.session_transaction() as session:
        session['usuario_id'] = user_id
        session['session_version'] = user['session_version']
        session['auth_stamp'] = identity
    return client, token.group(1)


def action(client, token, path, payload=None):
    return client.post(path, json=payload or {}, headers={
        'Accept': 'application/json', 'X-CSRF-Token': token})


def start(app, first=1, second=2):
    client, token = member(app, first)
    response = action(client, token, '/mensagens/iniciar', {'target_id': second})
    assert response.status_code == 201, response.text
    return client, token, response.json['conversation']['id']


def send(client, token, conversation, body='Olá, Bob!', nonce=None):
    return action(client, token, f'/mensagens/{conversation}/enviar', {
        'body': body, 'client_nonce': nonce or str(uuid4())})


def test_conversation_normalizes_pair_and_hides_user_secrets(app):
    client, _ = member(app, 1)
    assert client.get('/mensagens').status_code == 200
    client, token, conversation = start(app)
    bob, bob_token = member(app, 2)
    again = action(bob, bob_token, '/mensagens/iniciar', {'target_id': 1})
    assert again.status_code == 200
    assert again.json['conversation']['id'] == conversation
    data = client.get('/mensagens', headers={'Accept': 'application/json'}).json
    assert len(data['conversations']) == 1
    assert data['conversations'][0]['peer']['username'] == 'BOB'
    assert 'email' not in str(data) and 'senha' not in str(data)
    assert action(client, token, '/mensagens/iniciar', {'target_id': 1}).status_code == 400
    assert action(client, token, '/mensagens/iniciar', {'target_id': 999}).status_code == 404


def test_http_requires_auth_csrf_and_membership(app):
    anonymous = app.test_client()
    assert anonymous.get('/mensagens', headers={'Accept': 'application/json'}).status_code == 401
    client, token, conversation = start(app)
    assert client.post(f'/mensagens/{conversation}/enviar', json={'body': 'x'}).status_code == 400
    third, third_token = member(app, 3)
    for path in [f'/mensagens/{conversation}', f'/mensagens/{conversation}/historico']:
        assert third.get(path, headers={'Accept': 'application/json'}).status_code == 404
    assert send(third, third_token, conversation).status_code == 404
    assert action(third, third_token, f'/mensagens/{conversation}/lida', {'message_id': 1}).status_code == 404


def test_messages_validate_and_nonce_retries_are_idempotent(app):
    client, token, conversation = start(app)
    for body in ['', ' ', 'a' * 2001, 42]:
        assert send(client, token, conversation, body).status_code == 400
    assert send(client, token, conversation, 'Hello', 'not-a-uuid').status_code == 400
    nonce = str(uuid4())
    first = send(client, token, conversation, '<script>test</script>', nonce)
    assert first.status_code == 201
    retry = send(client, token, conversation, 'another text', nonce)
    assert retry.status_code == 200
    assert retry.json['message'] == first.json['message']
    data = client.get(f'/mensagens/{conversation}/historico').json
    assert len(data['messages']) == 1
    page = client.get(f'/mensagens/{conversation}')
    assert '&lt;script&gt;test&lt;/script&gt;' in page.text
    assert '<script>test</script>' not in page.text


def test_history_cursors_and_unread_receipts_are_scoped(app):
    alice, token, conversation = start(app)
    ids = [send(alice, token, conversation, text).json['message']['id'] for text in ['Um', 'Dois', 'Três']]
    bob, bob_token = member(app, 2)
    assert bob.get('/mensagens', headers={'Accept': 'application/json'}).json['unread_count'] == 3
    older = bob.get(f'/mensagens/{conversation}/historico?limit=2').json
    assert [m['body'] for m in older['messages']] == ['Dois', 'Três']
    assert older['has_more'] is True
    assert [m['body'] for m in bob.get(f'/mensagens/{conversation}/historico?before_id={ids[1]}').json['messages']] == ['Um']
    assert [m['body'] for m in bob.get(f'/mensagens/{conversation}/historico?after_id={ids[0]}').json['messages']] == ['Dois', 'Três']
    assert action(bob, bob_token, f'/mensagens/{conversation}/lida', {'message_id': ids[1]}).status_code == 200
    assert bob.get('/mensagens', headers={'Accept': 'application/json'}).json['unread_count'] == 1
    action(bob, bob_token, f'/mensagens/{conversation}/lida', {'message_id': ids[0]})
    assert bob.get('/mensagens', headers={'Accept': 'application/json'}).json['unread_count'] == 1
    assert alice.get('/mensagens', headers={'Accept': 'application/json'}).json['unread_count'] == 0
    assert bob.get(f'/mensagens/{conversation}/historico?before_id=bad').status_code == 400
    assert bob.get(f'/mensagens/{conversation}/historico?before_id=1&after_id=2').status_code == 400


@pytest.mark.parametrize('blocker,blocked', [(1, 2), (2, 1)])
def test_bilateral_blocks_hide_history_and_stop_sends(app, blocker, blocked):
    from criticard.social.models import Block
    client, token, conversation = start(app)
    send(client, token, conversation)
    with app.app_context():
        db = get_db()
        with db:
            db.execute(insert(Block).values(user_id=blocker, target_id=blocked))
    for user_id in [1, 2]:
        user, csrf = member(app, user_id)
        assert user.get(f'/mensagens/{conversation}/historico').status_code == 403
        assert send(user, csrf, conversation).status_code == 403
        assert user.get('/mensagens', headers={'Accept': 'application/json'}).json['conversations'] == []


def test_rate_limit_persists_and_idempotent_retry_does_not_consume_it(app):
    app.config['CHAT_RATE_LIMIT'] = 2
    client, token, conversation = start(app)
    nonce = str(uuid4())
    assert send(client, token, conversation, 'Primeira', nonce).status_code == 201
    assert send(client, token, conversation, 'retry', nonce).status_code == 200
    assert send(client, token, conversation, 'Segunda').status_code == 201
    another, another_token = member(app, 1)
    assert send(another, another_token, conversation, 'Terceira').status_code == 429
    assert len(client.get(f'/mensagens/{conversation}/historico').json['messages']) == 2


def test_deleting_account_anonymizes_messages_and_removes_membership(app):
    from criticard.chat.models import ConversationMember, Message
    client, token, conversation = start(app)
    send(client, token, conversation)
    with app.app_context():
        db = get_db()
        with db:
            db.execute(delete(User).where(User.id == 1))
        assert db.execute(select(Message.sender_id)).scalar() is None
        assert db.execute(select(ConversationMember.user_id).where(ConversationMember.user_id == 1)).fetchone() is None
    bob, _ = member(app, 2)
    data = bob.get(f'/mensagens/{conversation}/historico').json
    assert data['messages'][0]['sender'] is None
    assert 'ALICE' not in str(data)


def test_concurrent_starts_and_duplicate_sends_do_not_create_extra_rows(app):
    pairs = [member(app, 1) for _ in range(4)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(lambda pair: action(*pair, '/mensagens/iniciar', {'target_id': 2}), pairs))
    assert sorted(response.status_code for response in responses) == [200, 200, 200, 201]
    ids = {response.json['conversation']['id'] for response in responses}
    assert len(ids) == 1
    conversation = ids.pop()
    nonce = str(uuid4())
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(lambda pair: send(*pair, conversation, 'Só uma mensagem', nonce), pairs))
    assert sorted(response.status_code for response in responses) == [200, 200, 200, 201]
    assert len({response.json['message']['id'] for response in responses}) == 1
    assert len(pairs[0][0].get(f'/mensagens/{conversation}/historico').json['messages']) == 1


def test_invalid_large_ids_and_receipts_cannot_escape_conversation_scope(app):
    client, token, conversation = start(app)
    assert action(client, token, '/mensagens/iniciar', {'target_id': 10 ** 100}).status_code == 400
    assert client.get(f'/mensagens/{10 ** 100}/historico').status_code == 400
    assert client.get(f'/mensagens/{conversation}/historico?after_id={10 ** 100}').status_code == 400
    other = action(client, token, '/mensagens/iniciar', {'target_id': 3}).json['conversation']['id']
    other_message = send(client, token, other).json['message']['id']
    assert action(client, token, f'/mensagens/{conversation}/lida', {'message_id': other_message}).status_code == 404


def test_recovery_pages_over_one_hundred_messages_without_gaps(app):
    app.config['CHAT_RATE_LIMIT'] = 200
    client, token, conversation = start(app)
    ids = [send(client, token, conversation, f'Mensagem {number}').json['message']['id'] for number in range(105)]
    first = client.get(f'/mensagens/{conversation}/historico?after_id={ids[0]}&limit=100').json
    assert len(first['messages']) == 100 and first['has_more']
    last = client.get(f'/mensagens/{conversation}/historico?after_id={first["after_id"]}&limit=100').json
    assert [message['id'] for message in first['messages'] + last['messages']] == ids[1:]
    assert not last['has_more']


def test_message_dates_have_explicit_timezone_for_local_display(app):
    client, token, conversation = start(app)
    message = send(client, token, conversation).json['message']
    assert datetime.fromisoformat(message['created_at']).utcoffset() is not None
