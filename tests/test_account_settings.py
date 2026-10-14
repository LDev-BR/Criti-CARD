"""Account settings use temporary users, real CSRF and migrated databases."""
import hashlib
import importlib.util
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import insert, select, update
from werkzeug.security import check_password_hash, generate_password_hash

from criticard import create_app
from criticard.accounts.models import AccountToken
from criticard.db import get_db
from criticard.models import Card, User, utcnow
from criticard.security import session_identity
from criticard.social.models import Block, Follow, Friend


@pytest.fixture
def account_app(tmp_path):
    app = create_app({'TESTING': True, 'SECRET_KEY': 'settings-account-test-key',
        'DATABASE': str(tmp_path / 'settings.db'), 'UPLOAD_FOLDER': str(tmp_path / 'avatars'),
        'CAPA_FOLDER': str(tmp_path / 'covers'), 'ADM_USERNAME': '', 'ADM_SENHA': '',
        'SETTINGS_SECURITY_ATTEMPT_LIMIT': 30, 'SETTINGS_SECURITY_ATTEMPT_WINDOW': 300})
    if importlib.util.find_spec('criticard.accounts.settings') and 'account_settings' not in app.blueprints:
        from criticard.accounts.settings import bp
        app.register_blueprint(bp)
    if 'settings.index' not in app.view_functions:
        app.add_url_rule('/configuracoes', 'settings.index', lambda: 'Settings')
    with app.app_context():
        db = get_db()
        with db:
            for identity, name in [(1, 'ALICE'), (2, 'BOB'), (3, 'ADMIN')]:
                db.execute(insert(User).values(id=identity, username=name, nome=name.title(),
                    apelido='Leitor', about='Biografia pública', email=name.lower() + '@example.com',
                    senha=generate_password_hash('Password1!'), admin=int(identity == 3)))
            db.execute(insert(Card).values(titulo='Meu cartão', capa='cover.png', sobre='Crítica de ação',
                nota=87, author_id=1))
            db.execute(insert(Card).values(titulo='Cartão privado de Bob', capa='cover.png', sobre='Outro',
                nota=80, author_id=2))
    yield app
    app.extensions['database_engine'].dispose()


def member(app, identity=1):
    client = app.test_client()
    page = client.get('/')
    token = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
    with app.app_context():
        user = get_db().execute(select(User).where(User.id == identity)).fetchone()
        stamp = session_identity(user)
    with client.session_transaction() as session:
        session.update(usuario_id=identity, session_version=user['session_version'], auth_stamp=stamp)
    return client, token


def action(client, token, path='/configuracoes/conta/senha', payload=None, native=False):
    data = payload if payload is not None else {'current_password': 'Password1!',
        'new_password': 'Different2!', 'confirm_password': 'Different2!'}
    return client.post(path, **({'data': data} if native else {'json': data}),
        headers={'X-CSRF-Token': token})


def account(app, identity=1):
    with app.app_context():
        return get_db().execute(select(User).where(User.id == identity)).fetchone()


def test_password_change_preserves_current_session_and_revokes_other_sessions(account_app):
    client, token = member(account_app)
    other, _ = member(account_app)
    assert action(client, token).status_code == 200
    user = account(account_app)
    assert check_password_hash(user['senha'], 'Different2!') and user['session_version'] == 1
    assert client.get('/configuracoes/conta/exportar').status_code == 200
    assert other.get('/configuracoes/conta/exportar', headers={'Accept': 'application/json'}).status_code == 401
    assert check_password_hash(account(account_app, 2)['senha'], 'Password1!')


def test_two_requests_with_old_identity_cannot_both_change_password(account_app):
    from flask import request
    first, first_token = member(account_app)
    second, second_token = member(account_app)
    barrier = Barrier(2)

    def after_authentication():
        if request.path == '/configuracoes/conta/senha':
            barrier.wait(timeout=10)

    account_app.before_request_funcs[None].append(after_authentication)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(action, client, token) for client, token in ((first, first_token), (second, second_token))]
        statuses = [future.result(timeout=15).status_code for future in futures]
    assert sorted(statuses) == [200, 401]
    assert account(account_app)['session_version'] == 1


@pytest.mark.parametrize(('changes', 'field', 'status'), [
    ({'current_password': 'incorrect'}, 'current_password', 403),
    ({'current_password': 12}, 'current_password', 422),
    ({'current_password': 'a' * 1025}, 'current_password', 422),
    ({'new_password': 'short'}, 'new_password', 422),
    ({'new_password': 'A1!' + 'x' * 126}, 'new_password', 422),
    ({'new_password': ['Password2!']}, 'new_password', 422),
    ({'confirm_password': 'Wrong3!'}, 'confirm_password', 422),
])
def test_password_errors_are_specific_and_do_not_change_credentials(account_app, changes, field, status):
    client, token = member(account_app)
    before = account(account_app)
    payload = {'current_password': 'Password1!', 'new_password': 'Different2!', 'confirm_password': 'Different2!'}
    payload.update(changes)
    response = action(client, token, payload=payload)
    assert response.status_code == status and response.json['field'] == field
    assert account(account_app)['senha'] == before['senha']
    assert 'Password1!' not in response.text and 'Different2!' not in response.text


def test_legacy_long_current_password_is_accepted(account_app):
    legacy = 'x' * 800
    with account_app.app_context():
        db = get_db()
        with db:
            db.execute(update(User).where(User.id == 1).values(senha=generate_password_hash(legacy)))
    client, token = member(account_app)
    assert action(client, token, payload={'current_password': legacy,
        'new_password': 'Different2!', 'confirm_password': 'Different2!'}).status_code == 200


def test_change_invalidates_recovery_links_and_already_connected_socket(account_app):
    from criticard.accounts import service
    from criticard.chat.sockets import socketio
    client, token = member(account_app)
    socket = socketio.test_client(account_app, flask_test_client=client, namespace='/chat',
        auth={'csrf_token': token})
    assert socket.is_connected('/chat')
    raw = 'x' * 43
    with account_app.app_context():
        db = get_db()
        with db:
            db.execute(insert(AccountToken).values(user_id=1, token_hash=hashlib.sha256(raw.encode()).hexdigest(),
                purpose='reset', email_snapshot='alice@example.com', session_version=0,
                expires_at=utcnow() + timedelta(hours=1)))
        service.inspect_token(raw, 'reset')
    assert action(client, token).status_code == 200
    with account_app.app_context(), pytest.raises(service.InvalidAccountToken):
        service.inspect_token(raw, 'reset')
    result = socket.emit('join', {'conversation_id': 1}, namespace='/chat', callback=True)
    assert result['code'] == 401 and not socket.is_connected('/chat')


def test_logout_all_requires_password_and_ends_current_and_other_sessions(account_app):
    client, token = member(account_app)
    other, _ = member(account_app)
    assert action(client, token, '/configuracoes/conta/sessoes', {'current_password': 'wrong'}).status_code == 403
    response = action(client, token, '/configuracoes/conta/sessoes', {'current_password': 'Password1!'}, native=True)
    assert response.status_code == 302 and response.location == '/'
    assert account(account_app)['session_version'] == 1
    for browser in (client, other):
        assert browser.get('/configuracoes/conta/exportar', headers={'Accept': 'application/json'}).status_code == 401


def test_account_writes_require_csrf_and_login(account_app):
    client, token = member(account_app)
    assert client.post('/configuracoes/conta/senha', json={}).status_code == 400
    anonymous = account_app.test_client()
    anonymous.get('/')
    with anonymous.session_transaction() as session:
        anon_token = session['csrf_token']
    assert action(anonymous, anon_token).status_code == 401
    assert client.get('/configuracoes/conta/senha').status_code == 405


def test_security_budget_is_persistent_shared_between_security_actions_and_separate_from_login(account_app):
    account_app.config['SETTINGS_SECURITY_ATTEMPT_LIMIT'] = 2
    client, token = member(account_app)
    assert action(client, token, payload={'current_password': 'wrong'}).status_code in (403, 422)
    assert action(client, token, '/configuracoes/conta/sessoes', {'current_password': 'wrong'}).status_code == 403
    other, other_token = member(account_app)
    response = action(other, other_token, '/configuracoes/conta/sessoes', {'current_password': 'Password1!'})
    assert response.status_code == 429 and int(response.headers['Retry-After']) >= 1
    assert account(account_app)['session_version'] == 0
    with account_app.app_context():
        assert get_db().execute('SELECT attempts FROM form_attempts WHERE scope=?', ('settings_security',)).scalar() == 2


def test_native_password_error_redirect_does_not_retain_secrets(account_app):
    client, token = member(account_app)
    response = action(client, token, payload={'current_password': 'SECRET-incorrect',
        'new_password': 'Different2!', 'confirm_password': 'Wrong3!'}, native=True)
    assert response.status_code == 302 and response.location == '/configuracoes?secao=conta'
    with client.session_transaction() as session:
        assert 'SECRET-incorrect' not in str(dict(session)) and 'Different2!' not in str(dict(session))
        error = session['_settings_account_error']
        assert set(error) == {'field', 'message', 'action'}
        assert error['field'] == 'confirm_password' and error['action'] == 'change_password'
        assert error['message'] == 'As senhas precisam ser iguais.'


def test_native_session_error_metadata_is_field_specific_and_success_clears_it(account_app):
    client, token = member(account_app)
    response = action(client, token, '/configuracoes/conta/sessoes',
        {'current_password': 'SECRET-incorrect'}, native=True)
    assert response.status_code == 302
    with client.session_transaction() as session:
        error = session['_settings_account_error']
        assert set(error) == {'field', 'message', 'action'}
        assert error['field'] == 'current_password' and error['action'] == 'revoke_sessions'
        assert 'SECRET-incorrect' not in str(error)
    assert action(client, token).status_code == 200
    with client.session_transaction() as session:
        assert '_settings_account_error' not in session


def test_export_has_owner_data_and_omits_all_credentials_and_third_party_content(account_app):
    from criticard.backlog.models import BacklogItem
    from criticard.chat.models import Conversation, Message
    with account_app.app_context():
        db = get_db()
        with db:
            db.execute(insert(BacklogItem).values(user_id=1, work_id=1, status='planned', visibility='private'))
            db.execute(insert(Follow).values(user_id=1, target_id=2))
            db.execute(insert(Friend).values(user_low_id=1, user_high_id=2, requested_by=1, status='accepted'))
            conversation = db.execute(insert(Conversation).values(pair_low_id=1, pair_high_id=2).returning(Conversation.id)).scalar()
            db.execute(insert(Message).values(conversation_id=conversation, sender_id=1, body='Minha mensagem íntima', client_nonce=str(uuid4())))
            db.execute(insert(Message).values(conversation_id=conversation, sender_id=2, body='Segredo recebido de Bob', client_nonce=str(uuid4())))
    client, _ = member(account_app)
    response = client.get('/configuracoes/conta/exportar')
    assert response.status_code == 200 and response.mimetype == 'application/json'
    assert 'attachment;' in response.headers['Content-Disposition'] and response.headers['Cache-Control'] == 'no-store'
    data = response.json
    assert data['profile']['email'] == 'alice@example.com' and data['profile']['id'] == 1
    assert len(data['cards']) == len(data['backlog']) == len(data['follows']) == len(data['friends']) == len(data['messages']) == 1
    assert data['messages'][0]['body'] == 'Minha mensagem íntima'
    assert isinstance(data['preferences'], dict)
    for forbidden in ('bob@example.com', 'admin@example.com', 'Segredo recebido de Bob', 'Cartão privado de Bob',
        'senha', 'session_version', 'auth_stamp', 'client_nonce', 'token_hash', 'settings-account-test-key', '127.0.0.1'):
        assert forbidden not in response.text
    admin, _ = member(account_app, 3)
    assert admin.get('/configuracoes/conta/exportar').json['profile']['id'] == 3


def test_export_preserves_backlog_progress_units_and_saved_preferences(account_app):
    from criticard.backlog.models import BacklogItem
    from criticard.settings.service import save_preferences
    with account_app.app_context():
        db = get_db()
        with db:
            db.execute(insert(BacklogItem).values(user_id=1, work_id=1, status='in_progress',
                visibility='private', progress=12, progress_unit='episodes'))
        save_preferences(1, 'chat', {'chat_enter_send': False, 'chat_preview': False, 'chat_timestamps': True})
    client, _ = member(account_app)
    data = client.get('/configuracoes/conta/exportar').json
    assert data['backlog'][0]['progress'] == 12
    assert data['backlog'][0]['progress_unit'] == 'episodes'
    assert data['preferences']['chat_enter_send'] is False


def test_block_list_ownership_public_fields_search_and_clamped_pagination(account_app):
    from criticard.accounts.settings import blocked_users
    with account_app.app_context():
        db = get_db()
        with db:
            db.execute(insert(Block).values(user_id=1, target_id=2))
            db.execute(insert(Block).values(user_id=3, target_id=1))
            for identity in range(4, 29):
                db.execute(insert(User).values(id=identity, username=f'READER{identity}', nome=f'Reader {identity}',
                    apelido='Leitor', about='Público', email=f'private{identity}@example.com', senha='privatehash'))
                db.execute(insert(Block).values(user_id=1, target_id=identity))
        data = blocked_users(1, page=9999)
        assert data['total'] == 26 and data['pages'] == data['page'] == 2 and len(data['people']) == 2
        assert blocked_users(1, '@bob')['people'][0]['id'] == 2
        assert blocked_users(1, '%')['total'] == 0 and blocked_users(1, '_')['total'] == 0
        assert blocked_users(1, page=-5)['page'] == 1
        assert 'email' not in str(data) and 'privatehash' not in str(data)
        assert set(data['people'][0]) == {'id', 'username', 'nome', 'apelido', 'about', 'imagem', 'avatar_url'}


def test_unblock_cannot_remove_other_owners_block_and_redirect_is_local(account_app):
    with account_app.app_context():
        db = get_db()
        with db:
            db.execute(insert(Block).values(user_id=1, target_id=2))
            db.execute(insert(Block).values(user_id=3, target_id=2))
    client, token = member(account_app)
    path = '/configuracoes/bloqueados/2/desbloquear'
    assert client.post(path, json={}).status_code == 400
    response = action(client, token, path, {'user_id': 3, 'next': 'https://evil.test', 'page': '9999999', 'q': '@bob'}, native=True)
    assert response.status_code == 302 and response.location.startswith('/configuracoes?secao=bloqueados')
    with account_app.app_context():
        assert get_db().execute(select(Block.user_id).where(Block.target_id == 2)).fetchall() == [{'user_id': 3}]
