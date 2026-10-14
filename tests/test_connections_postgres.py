"""Real PostgreSQL serialization for explicit friendship and bilateral blocks."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from sqlalchemy import func, select

from criticard.db import get_db
from criticard.social.connections import change_friendship, connection_counts, list_connections
from criticard.social.models import Follow, Friend, Notification
from criticard.social.service import SocialError, set_block
from test_postgres import in_app, pg_app, pg_database_url


def test_postgres_crossed_duplicate_requests_require_explicit_acceptance(pg_app):
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda index: in_app(pg_app,
            lambda: change_friendship(1 if index % 2 else 2, 2 if index % 2 else 1, 'request')), range(6)))
    assert {result['state'] for result in results} == {'incoming', 'outgoing'}
    with pg_app.app_context():
        db = get_db()
        record = db.execute(select(Friend.__table__)).fetchone()
        assert record['status'] == 'pending'
        assert db.execute(select(func.count()).select_from(Friend)).scalar() == 1
        assert db.execute(select(func.count()).select_from(Notification).where(Notification.kind == 'friend_request')).scalar() == 1
        sender = record['requested_by']
        recipient = 2 if sender == 1 else 1
    with ThreadPoolExecutor(max_workers=4) as pool:
        accepted = list(pool.map(lambda _: in_app(pg_app, lambda: change_friendship(recipient, sender, 'accept')), range(4)))
    assert all(result['state'] == 'friends' for result in accepted)
    with pg_app.app_context():
        assert connection_counts(1)['friends'] == 1
        assert connection_counts(2)['incoming'] == 0
        assert get_db().execute(select(func.count()).select_from(Follow)).scalar() == 0
        assert get_db().execute(select(func.count()).select_from(Notification).where(Notification.kind == 'friend_accept')).scalar() == 1
        assert [p['username'] for p in list_connections(1, 'discover', '@bob')['people']] == ['BOB']


def test_postgres_block_and_invitation_race_cannot_leave_friendship(pg_app):
    barrier = Barrier(2)
    def invite():
        with pg_app.app_context():
            barrier.wait(timeout=5)
            try:
                change_friendship(1, 2, 'request')
                return 'requested'
            except SocialError as error:
                assert error.status == 403
                return 'blocked'
    def block():
        with pg_app.app_context():
            barrier.wait(timeout=5)
            return set_block(2, 1, True)
    with ThreadPoolExecutor(max_workers=2) as pool:
        invite_future, block_future = pool.submit(invite), pool.submit(block)
        assert invite_future.result(timeout=10) in ('requested', 'blocked')
        assert block_future.result(timeout=10)['blocked'] is True
    with pg_app.app_context():
        assert get_db().execute(select(Friend.id)).fetchone() is None
        assert get_db().execute(select(Notification.id).where(Notification.kind == 'friend_request')).fetchone() is None
        assert list_connections(1, 'discover', 'Bob')['people'] == []
