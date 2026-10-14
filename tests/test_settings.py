"""Preference ownership, validation, privacy and transactional service behavior."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event, current_thread
from uuid import uuid4

import pytest
from sqlalchemy import delete, event, func, select
from sqlalchemy.sql.dml import Update

from criticard.db import get_db
from criticard.models import User


def _member(app, user_id=1):
    import re
    from criticard.security import session_identity
    client = app.test_client()
    page = client.get('/')
    token = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
    with app.app_context():
        user = get_db().execute(select(User).where(User.id == user_id)).fetchone()
        stamp = session_identity(user)
    with client.session_transaction() as session:
        session['usuario_id'] = user_id
        session['session_version'] = user['session_version']
        session['auth_stamp'] = stamp
    return client, token


def _register_settings(app):
    # Allow this domain to run independently before factory integration lands.
    if 'settings' not in app.blueprints:
        from criticard.settings import bp
        app.register_blueprint(bp)


def test_http_settings_requires_login_csrf_and_session_ownership(app):
    from criticard.settings.service import get_preferences
    _register_settings(app)
    anonymous = app.test_client()
    assert anonymous.get('/configuracoes', headers={'Accept': 'application/json'}).status_code == 401
    client, token = _member(app)
    assert client.post('/configuracoes/chat', json={'chat_preview': False}).status_code == 400
    headers = {'X-CSRF-Token': token, 'Accept': 'application/json'}
    denied = client.post('/configuracoes/chat', json={'user_id': 2, 'chat_preview': False}, headers=headers)
    assert denied.status_code == 400 and denied.json['field'] == 'user_id'
    saved = client.post('/configuracoes/chat', json={'chat_preview': False}, headers=headers)
    assert saved.status_code == 200 and saved.json['preferences']['chat_preview'] is False
    with app.app_context():
        assert get_preferences(2)['chat_preview'] is True
    assert client.get('/configuracoes?secao=inexistente', headers=headers).status_code == 404
    assert client.post('/configuracoes/conta', json={}, headers=headers).status_code == 404


@pytest.mark.parametrize('payload', [[], True, None, {'chat_preview': 'false'}, {'chat_preview': 0},
                                      {'chat_preview': []}, {'chat_preview': False, 'unknown': 1}])
def test_http_json_types_are_strict(app, payload):
    _register_settings(app)
    client, token = _member(app)
    arguments = {'data': 'null', 'content_type': 'application/json'} if payload is None else {'json': payload}
    response = client.post('/configuracoes/chat', **arguments,
                           headers={'X-CSRF-Token': token, 'Accept': 'application/json'})
    assert response.status_code == 400


def test_html_unchecked_boxes_become_false_and_integer_is_converted(app):
    from criticard.settings.service import get_preferences
    _register_settings(app)
    client, token = _member(app)
    response = client.post('/configuracoes/chat', data={'csrf_token': token, 'chat_enter_send': 'on'})
    assert response.status_code == 302
    response = client.post('/configuracoes/feed', data={'csrf_token': token, 'feed_min_score': '75'})
    assert response.status_code == 302
    with app.app_context():
        preferences = get_preferences(1)
        assert preferences['chat_enter_send'] is True
        assert preferences['chat_preview'] is False
        assert preferences['chat_timestamps'] is False
        assert preferences['feed_min_score'] == 75
    response = client.post('/configuracoes/feed', data={'csrf_token': token, 'feed_min_score': '9' * 5000},
                           headers={'Accept': 'application/json'})
    assert response.status_code == 400


def test_reset_http_rejects_payload_and_preserves_other_sections(app):
    from criticard.settings.service import get_preferences, save_preferences
    _register_settings(app)
    client, token = _member(app)
    headers = {'X-CSRF-Token': token, 'Accept': 'application/json'}
    with app.app_context():
        save_preferences(1, 'chat', {'chat_preview': False})
        save_preferences(1, 'privacidade', {'message_policy': 'nobody'})
    assert client.post('/configuracoes/chat/restaurar', json={'user_id': 2}, headers=headers).status_code == 400
    response = client.post('/configuracoes/chat/restaurar', json={}, headers=headers)
    assert response.status_code == 200 and response.json['preferences']['chat_preview'] is True
    with app.app_context():
        assert get_preferences(1)['message_policy'] == 'nobody'


def test_privacy_applies_to_socketio_sends_and_http_start_and_send(app):
    from criticard.settings.service import save_preferences
    from criticard.chat.sockets import socketio
    client, token = _member(app)
    headers = {'X-CSRF-Token': token, 'Accept': 'application/json'}
    start = client.post('/mensagens/iniciar', json={'target_id': 2}, headers=headers)
    assert start.status_code == 201
    conversation = start.json['conversation']['id']
    socket = socketio.test_client(app, flask_test_client=client, namespace='/chat', auth={'csrf_token': token})
    assert socket.is_connected('/chat')
    try:
        assert socket.emit('join', {'conversation_id': conversation}, namespace='/chat', callback=True)['ok']
        with app.app_context():
            save_preferences(2, 'privacidade', {'message_policy': 'nobody'})
        payload = {'conversation_id': conversation, 'body': 'Proibida', 'client_nonce': str(uuid4())}
        sent = socket.emit('send_message', payload, namespace='/chat', callback=True)
        assert sent['ok'] is False and sent['code'] == 403
        assert client.post(f'/mensagens/{conversation}/enviar', json=payload, headers=headers).status_code == 403
        assert client.post('/mensagens/iniciar', json={'target_id': 2}, headers=headers).status_code == 403
        assert client.get(f'/mensagens/{conversation}/historico', headers=headers).status_code == 200
    finally:
        socket.disconnect(namespace='/chat')


def test_defaults_are_complete_and_read_does_not_create_rows(app):
    from criticard.settings.schema import DEFAULTS
    from criticard.settings.models import UserSettings
    from criticard.settings.service import get_preferences
    with app.app_context():
        assert len(DEFAULTS) == 28
        first = get_preferences(1)
        assert first == DEFAULTS
        first['message_policy'] = 'nobody'
        assert get_preferences(1)['message_policy'] == 'all'
        assert get_db().execute(select(func.count()).select_from(UserSettings)).scalar() == 0


def test_section_save_and_reset_preserve_other_preferences(app):
    from criticard.settings.service import get_preferences, reset_preferences, save_preferences
    with app.app_context():
        save_preferences(1, 'privacidade', {'message_policy': 'friends'})
        save_preferences(1, 'aparencia', {'text_size': 'large', 'reduce_motion': True})
        assert get_preferences(2)['text_size'] == 'standard'
        prefs = reset_preferences(1, 'aparencia')
        assert prefs['text_size'] == 'standard'
        assert prefs['message_policy'] == 'friends'


@pytest.mark.parametrize('section,payload,field', [
    ('aparencia', {'reduce_motion': 'false'}, 'reduce_motion'),
    ('aparencia', {'reduce_motion': 0}, 'reduce_motion'),
    ('aparencia', {'reduce_motion': []}, 'reduce_motion'),
    ('aparencia', {'text_size': ['large']}, 'text_size'),
    ('aparencia', {'text_size': 'giant'}, 'text_size'),
    ('aparencia', {'user_id': 2}, 'user_id'),
    ('aparencia', {'message_policy': 'nobody'}, 'message_policy'),
    ('feed', {'feed_min_score': True}, 'feed_min_score'),
    ('feed', {'feed_min_score': '50'}, 'feed_min_score'),
    ('feed', {'feed_min_score': -1}, 'feed_min_score'),
    ('feed', {'feed_min_score': 101}, 'feed_min_score'),
    ('feed', {'feed_category': 'missing'}, 'feed_category'),
    ('feed', {'feed_category': '\ud800'}, 'feed_category'),
    ('feed', ['feed_sort'], None),
])
def test_invalid_types_fields_and_values_rejected_without_writes(app, section, payload, field):
    from criticard.settings.service import SettingsError, get_preferences, save_preferences
    with app.app_context():
        before = get_preferences(1)
        with pytest.raises(SettingsError) as error:
            save_preferences(1, section, payload)
        assert error.value.field == field
        assert get_preferences(1) == before


def test_existing_categories_and_score_boundaries_are_valid(app):
    from criticard.settings.service import save_preferences
    with app.app_context():
        slug = get_db().execute('SELECT slug FROM categorias ORDER BY id LIMIT 1').fetchone()['slug']
        assert save_preferences(1, 'feed', {'feed_category': slug, 'feed_min_score': 100})['feed_min_score'] == 100
        assert save_preferences(1, 'feed', {'feed_category': '', 'feed_min_score': 0})['feed_category'] == ''


def test_concurrent_section_writes_do_not_lose_updates(app):
    from criticard.settings.service import get_preferences, save_preferences
    def save(section, data):
        with app.app_context():
            return save_preferences(1, section, data)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(save, 'aparencia', {'text_size': 'large'}),
                   pool.submit(save, 'privacidade', {'message_policy': 'nobody'})]
        for future in futures:
            future.result(timeout=15)
    with app.app_context():
        prefs = get_preferences(1)
        assert prefs['text_size'] == 'large'
        assert prefs['message_policy'] == 'nobody'


@pytest.mark.parametrize('operation', ['message', 'friend_request'])
def test_privacy_writer_lock_serializes_concurrent_interactions(app, operation):
    from criticard.chat.service import ChatError, send_message, start_conversation
    from criticard.settings.service import save_preferences
    from criticard.social.connections import change_friendship
    from criticard.social.service import SocialError
    with app.app_context():
        conversation = start_conversation(1, 2)[0]['id']
    locked, attempted, release = Event(), Event(), Event()
    engine = app.extensions['database_engine']

    def before_write(connection, cursor, statement, parameters, context, many):
        compiled = context.compiled
        if compiled is not None and isinstance(compiled.statement, Update) and compiled.statement.table.name == 'usuarios':
            if current_thread().name.startswith('settings-interaction'):
                attempted.set()

    def after_write(connection, cursor, statement, parameters, context, many):
        compiled = context.compiled
        if compiled is not None and isinstance(compiled.statement, Update) and compiled.statement.table.name == 'usuarios':
            if current_thread().name.startswith('settings-privacy'):
                locked.set()
                assert release.wait(timeout=10), 'Test must release the held writer lock'

    def change_privacy():
        with app.app_context():
            save_preferences(2, 'privacidade', {'message_policy': 'nobody', 'friend_request_policy': 'nobody'})

    def interact():
        with app.app_context():
            try:
                if operation == 'message':
                    send_message(1, conversation, 'Não deve chegar', str(uuid4()))
                else:
                    change_friendship(1, 2, 'request')
            except (ChatError, SocialError) as error:
                return error.status
            return 200

    event.listen(engine, 'before_cursor_execute', before_write)
    event.listen(engine, 'after_cursor_execute', after_write)
    try:
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix='settings-privacy') as writers, \
             ThreadPoolExecutor(max_workers=1, thread_name_prefix='settings-interaction') as actors:
            privacy = writers.submit(change_privacy)
            assert locked.wait(timeout=10)
            interaction = actors.submit(interact)
            try:
                assert attempted.wait(timeout=10)
            finally:
                release.set()
            privacy.result(timeout=15)
            assert interaction.result(timeout=15) == 403
    finally:
        release.set()
        event.remove(engine, 'before_cursor_execute', before_write)
        event.remove(engine, 'after_cursor_execute', after_write)


def test_settings_cascade_with_deleted_account(app):
    from criticard.settings.models import UserSettings
    from criticard.settings.service import save_preferences
    with app.app_context():
        save_preferences(2, 'chat', {'chat_preview': False})
        db = get_db()
        with db:
            db.execute(delete(User).where(User.id == 2))
        assert db.execute(select(UserSettings.user_id)).fetchall() == []


def test_message_policy_checks_destination_and_keeps_history_readable(app):
    from criticard.chat.service import ChatError, history, membership, send_message, start_conversation
    from criticard.settings.service import save_preferences
    from criticard.social.connections import change_friendship
    with app.app_context():
        conversation, _ = start_conversation(1, 2)
        send_message(1, conversation['id'], 'Anterior', str(uuid4()))
        save_preferences(2, 'privacidade', {'message_policy': 'nobody'})
        for operation in (lambda: start_conversation(1, 2),
                          lambda: send_message(1, conversation['id'], 'Proibida', str(uuid4())),
                          lambda: membership(1, conversation['id'], sending=True)):
            with pytest.raises(ChatError) as error:
                operation()
            assert error.value.status == 403
        assert history(1, conversation['id'])['messages'][0]['body'] == 'Anterior'
        # Only the destination's incoming policy applies.
        assert send_message(2, conversation['id'], 'Resposta', str(uuid4()))[1]
        save_preferences(2, 'privacidade', {'message_policy': 'friends'})
        with pytest.raises(ChatError):
            start_conversation(1, 2)
        change_friendship(1, 2, 'request')
        change_friendship(2, 1, 'accept')
        assert send_message(1, conversation['id'], 'Entre amigos', str(uuid4()))[1]


def test_friend_policy_is_target_following_actor_and_old_invites_remain_valid(app):
    from criticard.settings.service import save_preferences
    from criticard.social.connections import change_friendship
    from criticard.social.service import SocialError, set_follow
    with app.app_context():
        save_preferences(2, 'privacidade', {'friend_request_policy': 'following'})
        set_follow(1, 2, True)
        with pytest.raises(SocialError) as error:
            change_friendship(1, 2, 'request')
        assert error.value.status == 403
        set_follow(2, 1, True)
        pending = change_friendship(1, 2, 'request')
        save_preferences(2, 'privacidade', {'friend_request_policy': 'nobody'})
        assert change_friendship(1, 2, 'request') == pending
        assert change_friendship(2, 1, 'accept')['state'] == 'friends'
        change_friendship(1, 2, 'remove')
        with pytest.raises(SocialError):
            change_friendship(1, 2, 'request')


def test_notifications_disable_future_events_without_deleting_previous(app):
    from criticard.settings.service import save_preferences
    from criticard.social.connections import change_friendship
    from criticard.social.service import create_comment, set_follow, set_like
    from criticard.social.models import Notification
    with app.app_context():
        create_comment(2, 1, 'Anterior')
        save_preferences(1, 'notificacoes', {
            'notify_likes': False, 'notify_comments': False, 'notify_follows': False,
            'notify_friend_requests': False, 'notify_friend_accepts': False})
        set_like(2, 1, True)
        create_comment(2, 1, 'Novo')
        set_follow(2, 1, True)
        change_friendship(2, 1, 'request')
        change_friendship(1, 2, 'accept')
        kinds = get_db().execute(select(Notification.kind).where(Notification.recipient_id == 1)).fetchall()
        assert [row['kind'] for row in kinds] == ['comment']
        change_friendship(1, 2, 'remove')
        change_friendship(1, 2, 'request')
        change_friendship(2, 1, 'accept')
        kinds = get_db().execute(select(Notification.kind).where(Notification.recipient_id == 1)).fetchall()
        assert [row['kind'] for row in kinds] == ['comment']


def test_backlog_visibility_only_defaults_new_unspecified_items(app):
    from criticard.backlog.service import add_item, update_item
    from criticard.settings.service import save_preferences
    with app.app_context():
        works = get_db().execute('SELECT id FROM obras ORDER BY id LIMIT 3').fetchall()
        first, _ = add_item(1, {'obra_id': works[0]['id']})
        assert first['visibility'] == 'private'
        save_preferences(1, 'privacidade', {'backlog_visibility': 'public'})
        assert update_item(1, first['id'], {'status': 'completed'})['visibility'] == 'private'
        second, _ = add_item(1, {'obra_id': works[1]['id']})
        assert second['visibility'] == 'public'
        third, _ = add_item(1, {'obra_id': works[2]['id'], 'visibility': 'private'})
        assert third['visibility'] == 'private'
