"""Private notification filters, navigation and consistent read state."""
from datetime import timedelta

import pytest
from sqlalchemy import insert

from conftest import post, rows
from criticard.db import get_db
from criticard.models import utcnow
from criticard.social.models import Notification


@pytest.fixture
def notices(app):
    now = utcnow()
    with app.app_context():
        with get_db() as db:
            for identity, recipient, kind, read in (
                    (1, 1, 'like', False), (2, 1, 'comment', True),
                    (3, 1, 'follow', False), (4, 1, 'friend_request', False),
                    (5, 2, 'like', False)):
                db.execute(insert(Notification).values(id=identity, recipient_id=recipient,
                    actor_id=2 if recipient == 1 else 1, kind=kind,
                    card_id=1 if kind in ('like', 'comment') else None,
                    event_key=f'test:{identity}', created_at=now-timedelta(hours=identity),
                    read_at=now if read else None))


@pytest.mark.parametrize('query,ids', [
    ('state=unread', [4, 3, 1]), ('state=read', [2]),
    ('kind=comment', [2]), ('state=unread&kind=like', [1]),
    ('state=unread&kind=comment', []),
])
def test_filters_keep_counts_and_owner_scope(alice, notices, query, ids):
    response = alice.get('/social/notifications?' + query, headers={'Accept': 'application/json'})
    assert response.status_code == 200
    data = response.get_json()
    assert [item['id'] for item in data['notifications']] == ids
    assert data['total'] == len(ids)
    assert data['unread_count'] == 3
    assert response.headers['Cache-Control'] == 'no-store'


@pytest.mark.parametrize('query', ['state=wrong', 'kind=wrong', 'page=0', 'page=-1', 'page=text'])
def test_invalid_notification_filter_or_page_is_rejected(alice, query):
    assert alice.get('/social/notifications?' + query).status_code == 404


def test_open_marks_only_owned_notification_and_uses_server_destination(alice, app, notices):
    before = rows(app, 'SELECT read_at FROM notifications WHERE id=1')[0][0]
    assert before is None
    response = post(alice, '/social/notifications/1/open', {'next': 'https://untrusted.example/'})
    assert response.status_code == 302
    assert response.headers['Location'] == '/card/1'
    assert rows(app, 'SELECT read_at FROM notifications WHERE id=1')[0][0] is not None
    assert post(alice, '/social/notifications/5/open').status_code == 404
    assert rows(app, 'SELECT read_at FROM notifications WHERE id=5')[0][0] is None
    assert alice.post('/social/notifications/4/open').status_code == 400


def test_status_snapshot_does_not_read_notifications_or_expose_other_accounts(alice, app, notices):
    before = rows(app, 'SELECT id,read_at FROM notifications ORDER BY id')
    response = alice.get('/social/notifications/unread-count')
    data = response.get_json()
    assert data['unread_count'] == 3 and data['latest_id'] == 4
    assert data['latest_at'].endswith('+00:00')
    assert response.headers['Cache-Control'] == 'no-store'
    alice.get('/social/notifications')
    assert rows(app, 'SELECT id,read_at FROM notifications ORDER BY id') == before


def test_read_response_supports_filter_refresh_without_mutating_other_accounts(alice, app, notices):
    response = post(alice, '/social/notifications/1/read', headers={'Accept': 'application/json'})
    assert response.get_json()['unread_count'] == 2
    assert response.get_json()['latest_id'] == 4
    assert post(alice, '/social/notifications/1/read', headers={'Accept': 'application/json'}).status_code == 200
    assert rows(app, 'SELECT read_at FROM notifications WHERE id=5')[0][0] is None


def test_native_read_preserves_active_filters(alice, notices):
    response = post(alice, '/social/notifications/1/read', {'state': 'unread', 'kind': 'like'})
    assert response.status_code == 302
    assert 'state=unread' in response.headers['Location'] and 'kind=like' in response.headers['Location']


def test_notification_service_remains_usable_without_http_request(app, notices):
    from criticard.social.service import notifications_for_user
    with app.app_context():
        data = notifications_for_user(1)
        assert data['total'] == 4
        assert data['notifications'][-1]['target_url'] == '/card/1'
