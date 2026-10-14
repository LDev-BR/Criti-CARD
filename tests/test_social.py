"""Real HTTP and SQLite contracts for social interactions."""
import re
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import insert, select
from werkzeug.security import generate_password_hash

from criticard import create_app
from criticard.db import get_db
from criticard.models import Card, User


@pytest.fixture
def app(tmp_path):
    application = create_app({'TESTING': True, 'SECRET_KEY': 'social-test-key',
        'DATABASE': str(tmp_path / 'social.db'), 'UPLOAD_FOLDER': str(tmp_path / 'avatars'),
        'CAPA_FOLDER': str(tmp_path / 'covers')})
    with application.app_context():
        db = get_db()
        with db:
            for user_id, username in [(1, 'ALICE'), (2, 'BOB'), (3, 'ADMIN')]:
                db.execute(insert(User).values(id=user_id, username=username, nome=username.title(),
                    apelido='Leitor', about='Minha bio', email=username.lower() + '@example.com',
                    senha=generate_password_hash('Password1!'), admin=int(user_id == 3)))
            db.execute(insert(Card).values(id=1, titulo='Card da Alice', capa='legacy.png',
                sobre='Uma boa história', nota=90, author_id=1))
    yield application
    application.extensions['database_engine'].dispose()


def authenticated(app, user_id):
    client = app.test_client()
    page = client.get('/')
    token = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
    assert token, 'Use a real rendered CSRF token'
    response = client.post('/', data={'username': {1: 'alice', 2: 'bob', 3: 'admin'}[user_id],
        'senha': 'Password1!', 'csrf_token': token.group(1)})
    assert response.status_code == 302
    page = client.get('/social/notifications')
    token = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
    assert token, 'Use the token generated after the real login rotates the session'
    return client, token.group(1)


def action(client, token, path, payload=None, method='post'):
    return getattr(client, method)(path, json=payload or {}, headers={
        'Accept': 'application/json', 'X-CSRF-Token': token,
    })


def scalar(app, statement):
    with app.app_context():
        return get_db().execute(statement).scalar()


def bob_card(app):
    with app.app_context():
        db = get_db()
        with db:
            return db.execute(insert(Card).values(titulo='Card do Bob', capa='legacy.png',
                sobre='Outra história', nota=80, author_id=2).returning(Card.id)).scalar()


def test_like_is_idempotent_and_notifies_only_author(app):
    client, token = authenticated(app, 2)
    first = action(client, token, '/social/cards/1/like', {'liked': True})
    assert first.status_code == 200
    assert first.json == {'liked': True, 'like_count': 1, 'comment_count': 0}
    assert action(client, token, '/social/cards/1/like', {'liked': True}).json['like_count'] == 1
    owner, _ = authenticated(app, 1)
    assert owner.get('/social/notifications', headers={'Accept': 'application/json'}).json['unread_count'] == 1
    assert client.get('/social/notifications', headers={'Accept': 'application/json'}).json['unread_count'] == 0
    assert action(client, token, '/social/cards/1/like', method='delete').json['like_count'] == 0
    assert action(client, token, '/social/cards/1/like', method='delete').json['like_count'] == 0
    assert owner.get('/social/notifications', headers={'Accept': 'application/json'}).json['unread_count'] == 1


def test_like_requires_auth_csrf_and_existing_card(app, client):
    page = client.get('/')
    anonymous_token = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
    assert action(client, anonymous_token, '/social/cards/1/like', method='put').status_code == 401
    member, token = authenticated(app, 2)
    assert member.put('/social/cards/1/like', json={}).status_code == 400
    assert action(member, token, '/social/cards/999/like', method='put').status_code == 404
    assert action(member, token, '/social/cards/1/like', {'liked': 'false'}).status_code == 400


def test_concurrent_likes_have_one_row_and_one_notification(app):
    pairs = [authenticated(app, 2) for _ in range(5)]
    with ThreadPoolExecutor(max_workers=5) as workers:
        statuses = list(workers.map(lambda pair: action(*pair, '/social/cards/1/like', method='put').status_code, pairs))
    assert statuses == [200] * 5
    owner, _ = authenticated(app, 1)
    data = owner.get('/social/notifications', headers={'Accept': 'application/json'}).json
    assert len(data['notifications']) == data['unread_count'] == 1


def test_comments_validate_escape_edit_delete_and_moderate(app):
    member, token = authenticated(app, 2)
    assert action(member, token, '/social/cards/1/comments', {'body': ' '}).status_code == 400
    assert action(member, token, '/social/cards/1/comments', {'body': 'a' * 2001}).status_code == 400
    created = action(member, token, '/social/cards/1/comments', {'body': '<script>alert(1)</script>'})
    assert created.status_code == 201
    comment_id = created.json['comment']['id']
    public = app.test_client().get('/social/cards/1/comments')
    assert public.status_code == 200
    assert '&lt;script&gt;alert(1)&lt;/script&gt;' in public.text
    assert '<script>alert(1)</script>' not in public.text
    owner, owner_token = authenticated(app, 1)
    assert action(owner, owner_token, f'/social/comments/{comment_id}/edit', {'body': 'Vandalizado'}).status_code == 403
    assert action(owner, owner_token, f'/social/comments/{comment_id}/delete').status_code == 403
    assert action(member, token, f'/social/comments/{comment_id}/edit', {'body': 'Editado'}).json['comment']['body'] == 'Editado'
    assert owner.get('/social/notifications', headers={'Accept': 'application/json'}).json['unread_count'] == 1
    admin, admin_token = authenticated(app, 3)
    assert action(admin, admin_token, f'/social/comments/{comment_id}/delete').status_code == 200
    assert owner.get('/social/notifications', headers={'Accept': 'application/json'}).json['unread_count'] == 1


def test_self_actions_do_not_notify_and_follow_is_idempotent(app):
    owner, token = authenticated(app, 1)
    assert action(owner, token, '/social/cards/1/like', method='put').status_code == 200
    assert action(owner, token, '/social/cards/1/comments', {'body': 'Meu comentário'}).status_code == 201
    assert owner.get('/social/notifications', headers={'Accept': 'application/json'}).json['unread_count'] == 0
    assert action(owner, token, '/social/users/1/follow', {'following': True}).status_code == 400
    assert action(owner, token, '/social/users/2/follow', {'following': True}).json['following'] is True
    assert action(owner, token, '/social/users/2/follow', {'following': True}).json['following'] is True
    target, _ = authenticated(app, 2)
    assert target.get('/social/notifications', headers={'Accept': 'application/json'}).json['unread_count'] == 1
    assert action(owner, token, '/social/users/2/follow', {'following': False}).json['following'] is False
    assert action(owner, token, '/social/users/2/follow', {'following': False}).json['following'] is False
    assert target.get('/social/notifications', headers={'Accept': 'application/json'}).json['unread_count'] == 1
    assert action(owner, token, '/social/users/2/follow', {'following': True}).json['following'] is True
    assert target.get('/social/notifications', headers={'Accept': 'application/json'}).json['unread_count'] == 1


def test_blocks_are_bilateral_and_remove_existing_follows(app):
    other_card = bob_card(app)
    alice, alice_token = authenticated(app, 1)
    bob, bob_token = authenticated(app, 2)
    assert action(alice, alice_token, '/social/users/2/follow', {'following': True}).status_code == 200
    assert action(bob, bob_token, '/social/users/1/follow', {'following': True}).status_code == 200
    assert action(alice, alice_token, '/social/users/2/block', {'blocked': True}).json['blocked'] is True
    assert action(alice, alice_token, '/social/users/1/block', {'blocked': True}).status_code == 400
    for member, token, target, card in [(alice, alice_token, 2, other_card), (bob, bob_token, 1, 1)]:
        assert action(member, token, f'/social/users/{target}/follow', {'following': True}).status_code == 403
        assert action(member, token, f'/social/cards/{card}/like', method='put').status_code == 403
        assert action(member, token, f'/social/cards/{card}/comments', {'body': 'Indesejado'}).status_code == 403
    from criticard.social.models import Follow
    from sqlalchemy import func
    assert scalar(app, select(func.count()).select_from(Follow)) == 0
    from criticard.social.service import users_blocked
    with app.app_context():
        assert users_blocked(1, 2) and users_blocked(2, 1)
    assert action(alice, alice_token, '/social/users/2/block', {'blocked': False}).json['blocked'] is False
    assert action(bob, bob_token, '/social/cards/1/like', method='put').status_code == 200


def test_reports_validate_target_and_only_admin_can_resolve(app):
    member, token = authenticated(app, 2)
    for target_type, target_id in [('card', 999), ('comment', 999), ('user', 999), ('other', 1)]:
        assert action(member, token, '/social/reports', {'target_type': target_type, 'target_id': target_id, 'reason': 'Spam'}).status_code in (400, 404)
    assert action(member, token, '/social/reports', {'target_type': 'card', 'target_id': 1, 'reason': ' '}).status_code == 400
    report = action(member, token, '/social/reports', {'target_type': 'card', 'target_id': 1, 'reason': '<b>Spam</b>'})
    assert report.status_code == 201
    report_id = report.json['report']['id']
    assert member.get('/social/moderation', headers={'Accept': 'application/json'}).status_code == 403
    assert action(member, token, f'/social/reports/{report_id}/resolve').status_code == 403
    admin, admin_token = authenticated(app, 3)
    panel = admin.get('/social/moderation')
    assert '&lt;b&gt;Spam&lt;/b&gt;' in panel.text
    assert action(admin, admin_token, f'/social/reports/{report_id}/resolve').json['report']['status'] == 'resolved'
    assert action(admin, admin_token, f'/social/reports/{report_id}/resolve').json['report']['status'] == 'resolved'


def test_notification_owner_can_mark_own_only_and_pagination_counts(app):
    member, token = authenticated(app, 2)
    assert action(member, token, '/social/cards/1/like', method='put').status_code == 200
    owner, owner_token = authenticated(app, 1)
    listing = owner.get('/social/notifications', headers={'Accept': 'application/json'})
    assert listing.status_code == 200
    notification = listing.json['notifications'][0]
    notification_id = notification['id']
    assert action(member, token, f'/social/notifications/{notification_id}/read').status_code == 404
    assert action(owner, owner_token, f'/social/notifications/{notification_id}/read').json['unread_count'] == 0
    assert action(owner, owner_token, f'/social/notifications/{notification_id}/read').json['unread_count'] == 0
    action(member, token, '/social/cards/1/comments', {'body': 'Gostei!'})
    assert action(owner, owner_token, '/social/notifications/read-all').json['unread_count'] == 0
    assert member.get('/social/notifications?user_id=1', headers={'Accept': 'application/json'}).json['notifications'] == []


def test_forms_work_without_javascript_and_state_counts_include_zero(app):
    member, token = authenticated(app, 2)
    response = member.post('/social/cards/1/like', data={'liked': 'true', 'csrf_token': token})
    assert response.status_code == 302
    response = member.post('/social/cards/1/comments', data={'body': 'Sem JavaScript', 'csrf_token': token}, follow_redirects=True)
    assert response.status_code == 200 and 'Sem JavaScript' in response.text
    from criticard.social.service import card_social_state
    with app.app_context():
        assert card_social_state([1, 999], 2) == {
            1: {'liked': True, 'like_count': 1, 'comment_count': 1},
            999: {'liked': False, 'like_count': 0, 'comment_count': 0},
        }


@pytest.mark.parametrize('payload', [[], None, {'body': '\0'}, {'body': ['text']}, {'body': 123}])
def test_invalid_comment_payloads_return_validation_error(app, payload):
    member, token = authenticated(app, 2)
    response = member.post('/social/cards/1/comments', json=payload,
        headers={'Accept': 'application/json', 'X-CSRF-Token': token})
    assert response.status_code == 400


@pytest.mark.parametrize('payload', [
    {'target_type': [], 'target_id': 1, 'reason': 'Spam'},
    {'target_type': 'card', 'target_id': 2**100, 'reason': 'Spam'},
    {'target_type': 'card', 'target_id': 1.5, 'reason': 'Spam'},
    {'target_type': 'card', 'target_id': True, 'reason': 'Spam'},
    {'target_type': 'card', 'target_id': 1, 'reason': '\0'},
])
def test_invalid_report_payloads_return_validation_error(app, payload):
    member, token = authenticated(app, 2)
    assert action(member, token, '/social/reports', payload).status_code == 400


def test_oversized_ids_are_rejected_without_database_overflow(app):
    member, token = authenticated(app, 2)
    giant = 2**100
    assert action(member, token, f'/social/cards/{giant}/like', method='put').status_code == 404
    assert member.get(f'/social/cards/{giant}/comments').status_code == 404
    assert action(member, token, f'/social/users/{giant}/follow', method='put').status_code == 404
    assert action(member, token, f'/social/notifications/{giant}/read').status_code == 404


def test_notifications_paginate_and_read_all_marks_all_pages(app):
    member, token = authenticated(app, 2)
    for number in range(33):
        assert action(member, token, '/social/cards/1/comments', {'body': f'Comentário {number}'}).status_code == 201
    owner, owner_token = authenticated(app, 1)
    first = owner.get('/social/notifications', headers={'Accept': 'application/json'}).json
    second = owner.get('/social/notifications?page=2', headers={'Accept': 'application/json'}).json
    assert len(first['notifications']) == 30 and len(second['notifications']) == 3
    assert first['unread_count'] == second['unread_count'] == first['total'] == 33
    assert {n['id'] for n in first['notifications']}.isdisjoint(n['id'] for n in second['notifications'])
    assert owner.get('/social/notifications?page=' + str(2**100), headers={'Accept': 'application/json'}).status_code == 404
    assert action(owner, owner_token, '/social/notifications/read-all').json['unread_count'] == 0


def test_public_comments_do_not_expose_account_secrets_and_ignore_author_forgery(app):
    member, token = authenticated(app, 2)
    created = action(member, token, '/social/cards/1/comments', {'body': 'Texto público', 'author_id': 1})
    assert created.status_code == 201 and created.json['comment']['author_id'] == 2
    listing = app.test_client().get('/social/cards/1/comments', headers={'Accept': 'application/json'})
    assert listing.status_code == 200
    assert listing.json['comments'][0]['username'] == 'BOB'
    assert 'senha' not in listing.json['comments'][0] and 'email' not in listing.json['comments'][0]


def test_report_forms_accept_all_target_types_and_resolution_never_deletes_content(app):
    member, token = authenticated(app, 2)
    comment_id = action(member, token, '/social/cards/1/comments', {'body': 'Texto mantido'}).json['comment']['id']
    admin, admin_token = authenticated(app, 3)
    for target_type, target_id in [('card', 1), ('comment', comment_id), ('user', 1)]:
        form = member.get(f'/social/reports?target_type={target_type}&target_id={target_id}')
        assert form.status_code == 200
        report = action(member, token, '/social/reports', {'target_type': target_type, 'target_id': target_id, 'reason': 'Analisar conteúdo'})
        assert report.status_code == 201
        assert action(admin, admin_token, f"/social/reports/{report.json['report']['id']}/resolve").status_code == 200
    assert member.get('/social/cards/1/comments', headers={'Accept': 'application/json'}).json['total'] == 1


def test_deleted_comment_identity_is_never_reused_and_new_comment_notifies(app):
    member, token = authenticated(app, 2)
    created = action(member, token, '/social/cards/1/comments', {'body': 'Primeiro comentário'}).json['comment']['id']
    assert action(member, token, f'/social/comments/{created}/delete').status_code == 200
    next_id = action(member, token, '/social/cards/1/comments', {'body': 'Novo comentário'}).json['comment']['id']
    assert next_id > created
    owner, _ = authenticated(app, 1)
    assert owner.get('/social/notifications', headers={'Accept': 'application/json'}).json['unread_count'] == 2


def test_comment_moderation_service_checks_stored_admin_role(app):
    owner, token = authenticated(app, 1)
    response = action(owner, token, '/social/cards/1/comments', {'body': 'Texto da autora'})
    assert response.status_code == 201
    comment_id = response.json['comment']['id']
    from criticard.social import service
    with app.app_context():
        with pytest.raises(service.SocialError) as rejected:
            service.delete_comment(2, comment_id, admin=True)
        assert rejected.value.status == 403
        assert service.delete_comment(3, comment_id, admin=True) == 1
