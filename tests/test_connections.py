"""Friendship rules exercised against migrated, isolated SQLite databases."""
from concurrent.futures import ThreadPoolExecutor
from importlib import import_module
from threading import Barrier

import pytest
from sqlalchemy import delete, event, func, insert, select, update
from sqlalchemy.exc import IntegrityError

from criticard import create_app
from criticard.db import get_db
from criticard.models import User
from criticard.social.models import Block, Follow, Notification
from criticard.social import service


@pytest.fixture
def app(tmp_path):
    application = create_app({'TESTING': True, 'SECRET_KEY': 'connections-test-key',
        'DATABASE': str(tmp_path / 'connections.db'), 'UPLOAD_FOLDER': str(tmp_path / 'avatars'),
        'CAPA_FOLDER': str(tmp_path / 'covers')})
    with application.app_context():
        db = get_db()
        with db:
            for identity, username, name in [(1, 'ALICE', 'Alice'), (2, 'BOB', 'Bob'),
                                             (3, 'CAROL', 'Carolina'), (4, 'INACTIVE', 'Inactive')]:
                db.execute(insert(User).values(id=identity, username=username, nome=name,
                    apelido='Leitor', about='Bio pública', email=f'{username.lower()}@example.test',
                    senha='private-hash', search_name=name.casefold(), active=int(identity != 4)))
    yield application
    application.extensions['database_engine'].dispose()


def connections():
    return import_module('criticard.social.connections')


def friend_model():
    return import_module('criticard.social.models').Friend


def test_requests_retries_and_crossed_requests_stay_pending(app):
    with app.app_context():
        api = connections()
        assert api.relationship(1, 2) == {'state': 'none', 'id': None}
        requested = api.change_friendship(1, 2, 'request')
        assert requested['state'] == 'outgoing' and isinstance(requested['id'], int)
        assert api.change_friendship(1, 2, 'request') == requested
        assert api.change_friendship(2, 1, 'request') == {'state': 'incoming', 'id': requested['id']}
        assert api.relationship(1, 2) == requested
        assert get_db().execute(select(func.count()).select_from(friend_model())).scalar() == 1
        assert service.unread_count(2) == 1 and service.unread_count(1) == 0
        notice = service.notifications_for_user(2)['notifications'][0]
        assert notice['kind'] == 'friend_request'
        assert str(requested['id']) in notice['event_key'].split(':')
        assert api.connection_counts(1)['outgoing'] == api.connection_counts(2)['incoming'] == 1


def test_explicit_accept_is_recipient_only_and_notifies_requester_once(app):
    with app.app_context():
        api = connections()
        pending = api.change_friendship(1, 2, 'request')
        with pytest.raises(service.SocialError) as rejected:
            api.change_friendship(1, 2, 'accept')
        assert rejected.value.status == 403
        accepted = {'state': 'friends', 'id': pending['id']}
        assert api.change_friendship(2, 1, 'accept') == accepted
        assert api.change_friendship(2, 1, 'accept') == accepted
        assert api.relationship(1, 2) == accepted
        assert service.unread_count(1) == 1 and service.unread_count(2) == 0
        assert service.notifications_for_user(1)['notifications'][0]['kind'] == 'friend_accept'
        assert api.connection_counts(1)['friends'] == api.connection_counts(2)['friends'] == 1
        assert service.user_social_state(2, 1)['friend_count'] == 1
        assert service.user_social_state(2, 1)['friendship'] == accepted
        assert service.user_social_state(2)['friendship'] == {'state': 'none', 'id': None}


@pytest.mark.parametrize('action,actor,target,wrong_actor,wrong_target', [
    ('decline', 2, 1, 1, 2), ('cancel', 1, 2, 2, 1),
])
def test_pending_deletion_checks_role_and_removes_stale_request_notice(
        app, action, actor, target, wrong_actor, wrong_target):
    with app.app_context():
        api = connections()
        first = api.change_friendship(1, 2, 'request')
        with pytest.raises(service.SocialError) as rejected:
            api.change_friendship(wrong_actor, wrong_target, action)
        assert rejected.value.status == 403
        assert api.relationship(1, 2) == first
        assert api.change_friendship(actor, target, action) == {'state': 'none', 'id': None}
        assert api.change_friendship(actor, target, action) == {'state': 'none', 'id': None}
        assert service.unread_count(2) == 0
        assert service.notifications_for_user(2)['total'] == 0
        second = api.change_friendship(1, 2, 'request')
        assert second['id'] > first['id']
        assert service.unread_count(2) == 1


@pytest.mark.parametrize('actor,target', [(1, 2), (2, 1)])
def test_either_friend_can_remove_friendship_without_changing_follow(app, actor, target):
    with app.app_context():
        api = connections()
        service.set_follow(1, 2, True)
        assert api.relationship(1, 2) == {'state': 'none', 'id': None}
        api.change_friendship(1, 2, 'request')
        api.change_friendship(2, 1, 'accept')
        for action in ('cancel', 'decline'):
            with pytest.raises(service.SocialError):
                api.change_friendship(actor, target, action)
        assert api.change_friendship(actor, target, 'remove') == {'state': 'none', 'id': None}
        assert api.change_friendship(actor, target, 'remove') == {'state': 'none', 'id': None}
        assert service.user_social_state(2, 1)['following'] is True
        assert api.connection_counts(1)['friends'] == 0


def test_remove_cannot_bypass_pending_role_permissions(app):
    with app.app_context():
        api = connections()
        pending = api.change_friendship(1, 2, 'request')
        for actor, target in [(1, 2), (2, 1)]:
            with pytest.raises(service.SocialError):
                api.change_friendship(actor, target, 'remove')
        assert api.relationship(1, 2) == pending


@pytest.mark.parametrize('user_id,target_id,action,status', [
    (1, 1, 'request', 400), (1, 4, 'request', 404), (4, 1, 'request', 403),
    (1, 999, 'request', 404), (999, 1, 'request', 404), (1, 2**100, 'request', 404),
    (True, 2, 'request', 404), (1, 2, 'unknown', 400), (1, 2, [], 400),
    (1, 2, 'accept', 400),
])
def test_friendship_rejects_invalid_people_and_actions(app, user_id, target_id, action, status):
    with app.app_context(), pytest.raises(service.SocialError) as rejected:
        connections().change_friendship(user_id, target_id, action)
    assert rejected.value.status == status


@pytest.mark.parametrize('target_id', [2**100, True, None])
def test_block_identifier_validation_runs_before_reserving_writer(app, target_id):
    with app.app_context(), pytest.raises(service.SocialError) as rejected:
        service.set_block(1, target_id, True)
    assert rejected.value.status == 404


def test_navigation_request_count_ignores_inactive_and_blocked_people(app):
    with app.app_context():
        api = connections()
        api.change_friendship(2, 1, 'request')
        api.change_friendship(3, 1, 'request')
        assert api.incoming_request_count(1) == 2
        db = get_db()
        with db:
            db.execute(update(User).where(User.id == 2).values(active=0))
        assert api.incoming_request_count(1) == 1
        service.set_block(1, 3, True)
        assert api.incoming_request_count(1) == 0


@pytest.mark.parametrize('accepted', [False, True])
def test_bilateral_block_removes_friendship_and_pending_notification(app, accepted):
    with app.app_context():
        api = connections()
        api.change_friendship(1, 2, 'request')
        if accepted:
            api.change_friendship(2, 1, 'accept')
        service.set_block(2, 1, True)
        assert api.relationship(1, 2) == api.relationship(2, 1) == {'state': 'none', 'id': None}
        assert get_db().execute(select(func.count()).select_from(friend_model())).scalar() == 0
        assert service.notifications_for_user(2)['total'] == 0
        for actor, target in [(1, 2), (2, 1)]:
            with pytest.raises(service.SocialError) as rejected:
                api.change_friendship(actor, target, 'request')
            assert rejected.value.status == 403
            assert api.list_connections(actor, 'discover')['people'][0]['id'] == 3
        service.set_block(2, 1, False)
        assert api.relationship(1, 2) == {'state': 'none', 'id': None}


def test_counts_lists_and_search_use_public_visible_people(app):
    with app.app_context():
        api = connections()
        api.change_friendship(1, 2, 'request')
        api.change_friendship(2, 1, 'accept')
        api.change_friendship(3, 1, 'request')
        service.set_follow(1, 2, True)
        service.set_follow(3, 1, True)
        assert api.connection_counts(1) == {'friends': 1, 'incoming': 1, 'outgoing': 0,
                                          'followers': 1, 'following': 1, 'discover': 2}
        expected_people = {'friends': [2], 'incoming': [3], 'outgoing': [],
                           'followers': [3], 'following': [2], 'discover': [2, 3]}
        for tab, identities in expected_people.items():
            listing = api.list_connections(1, tab)
            assert [person['id'] for person in listing['people']] == identities
            assert listing['total'] == len(identities)
            assert listing['page'] == listing['pages'] == 1
            assert listing['counts'] == api.connection_counts(1)
            for person in listing['people']:
                assert set(person) == {'id', 'username', 'nome', 'apelido', 'about', 'imagem',
                                       'following', 'friendship'}
        bob = api.list_connections(1, 'following')['people'][0]
        assert bob['following'] is True and bob['friendship']['state'] == 'friends'
        assert api.list_connections(1, 'discover', '  carOLina  ')['people'][0]['id'] == 3
        assert api.list_connections(1, 'discover', '%')['total'] == 0
        assert api.list_connections(1, 'discover', '_')['total'] == 0
        service.set_block(3, 1, True)
        db = get_db()
        with db:
            db.execute(update(User).where(User.id == 2).values(active=0))
        assert api.connection_counts(1) == dict.fromkeys(expected_people, 0)
        assert api.list_connections(1, 'discover')['people'] == []


def test_lists_paginate_stably_and_bound_invalid_query_and_page(app):
    with app.app_context():
        api = connections()
        db = get_db()
        with db:
            for identity in range(5, 32):
                db.execute(insert(User).values(id=identity, username=f'PERSON{identity:02}',
                    nome='Pessoa', apelido='Leitor', about='Bio', email=f'person{identity}@example.test',
                    senha='private-hash'))
        first, second = api.list_connections(1, 'discover'), api.list_connections(1, 'discover', page=2)
        assert first['total'] == second['total'] == 29
        assert len(first['people']) == 24 and len(second['people']) == 5
        assert first['pages'] == second['pages'] == 2
        assert {p['id'] for p in first['people']}.isdisjoint(p['id'] for p in second['people'])
        for kwargs in ({'page': 3}, {'page': 2**100}, {'tab': 'invalid'},
                       {'query': '\0'}, {'query': []}, {'query': 'a' * 201}):
            with pytest.raises(service.SocialError):
                api.list_connections(1, **kwargs)


def test_discovery_accepts_username_at_prefix_and_preserves_display_query(app):
    with app.app_context():
        api = connections()
        listing = api.list_connections(1, 'discover', '  @bOb  ')
        assert [person['id'] for person in listing['people']] == [2]
        assert listing['query'] == '@bOb'
        assert api.list_connections(1, 'discover', 'Carolina')['people'][0]['id'] == 3


def test_list_query_count_is_bounded_for_a_full_page(app):
    with app.app_context():
        api = connections()
        db = get_db()
        with db:
            for identity in range(5, 31):
                db.execute(insert(User).values(id=identity, username=f'PERSON{identity:02}',
                    nome='Pessoa', apelido='Leitor', about='Bio', email=f'person{identity}@example.test',
                    senha='private-hash'))
        statements = []
        def observed(_connection, _cursor, statement, _parameters, _context, _many):
            statements.append(statement)
        engine = app.extensions['database_engine']
        event.listen(engine, 'before_cursor_execute', observed)
        try:
            assert len(api.list_connections(1, 'discover')['people']) == 24
        finally:
            event.remove(engine, 'before_cursor_execute', observed)
        assert len(statements) <= 12, 'Relationship/follow queries must be batched, not per person'


def test_deleting_a_person_cascades_all_friendships(app):
    with app.app_context():
        api = connections()
        api.change_friendship(1, 2, 'request')
        api.change_friendship(2, 1, 'accept')
        api.change_friendship(3, 1, 'request')
        db = get_db()
        with db:
            db.execute(delete(User).where(User.id == 1))
        assert db.execute(select(func.count()).select_from(friend_model())).scalar() == 0
        assert api.connection_counts(2)['friends'] == api.connection_counts(3)['outgoing'] == 0


@pytest.mark.parametrize('values', [
    {'user_low_id': 2, 'user_high_id': 1, 'requested_by': 1, 'status': 'pending'},
    {'user_low_id': 1, 'user_high_id': 1, 'requested_by': 1, 'status': 'pending'},
    {'user_low_id': 1, 'user_high_id': 2, 'requested_by': 3, 'status': 'pending'},
    {'user_low_id': 1, 'user_high_id': 2, 'requested_by': 1, 'status': 'other'},
])
def test_friendship_schema_enforces_pair_requester_and_status(app, values):
    with app.app_context():
        db = get_db()
        with pytest.raises(IntegrityError), db:
            db.execute(insert(friend_model()).values(**values))


def test_concurrent_requests_preserve_one_pending_row_and_notification(app):
    barrier = Barrier(6)
    def request(actor):
        with app.app_context():
            barrier.wait(timeout=10)
            return connections().change_friendship(actor, 3 - actor, 'request')
    with ThreadPoolExecutor(max_workers=6) as workers:
        results = list(workers.map(request, [1, 2, 1, 2, 1, 2]))
    assert len({result['id'] for result in results}) == 1
    assert {result['state'] for result in results} == {'incoming', 'outgoing'}
    with app.app_context():
        db = get_db()
        assert db.execute(select(func.count()).select_from(friend_model())).scalar() == 1
        assert db.execute(select(func.count()).select_from(Notification).where(
            Notification.kind == 'friend_request')).scalar() == 1


def test_concurrent_block_and_request_cannot_leave_friendship(app):
    barrier = Barrier(2)
    def act(block):
        with app.app_context():
            barrier.wait(timeout=10)
            if block:
                return service.set_block(2, 1, True)
            try:
                return connections().change_friendship(1, 2, 'request')
            except service.SocialError as error:
                assert error.status == 403
    with ThreadPoolExecutor(max_workers=2) as workers:
        list(workers.map(act, [True, False]))
    with app.app_context():
        assert connections().relationship(1, 2) == {'state': 'none', 'id': None}
        db = get_db()
        assert db.execute(select(func.count()).select_from(friend_model())).scalar() == 0
        assert db.execute(select(func.count()).select_from(Block)).scalar() == 1
        assert service.unread_count(2) == 0
