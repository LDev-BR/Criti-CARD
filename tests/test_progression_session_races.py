"""Account changes between request authentication and the action lock."""
import pytest
from sqlalchemy import delete, insert, update

from conftest import post, rows
from criticard.backlog import service as backlog
from criticard.db import get_db
from criticard.models import Card, User
from criticard.social import service as social


def action_state(app):
    return {
        table: rows(app, f'SELECT * FROM {table} ORDER BY 1')
        for table in ('backlog_items', 'comments', 'notifications', 'experience_events',
                      'progression_profiles', 'achievement_grants', 'reward_grants')
    }


@pytest.mark.parametrize('flow', ['backlog_add', 'backlog_update', 'comment'])
@pytest.mark.parametrize('json_response', [False, True], ids=['html', 'json'])
@pytest.mark.parametrize('change,status', [
    ('revoke', 401), ('password', 401), ('inactive', 403), ('delete', 404),
])
def test_action_rechecks_locked_account_without_persisting_action(
        alice, app, monkeypatch, flow, json_response, change, status):
    with app.app_context():
        if flow == 'backlog_update':
            item, _ = backlog.add_item(1, dict(obra_id=1))
            path, data = f"/backlog/{item['id']}/update", dict(status='completed')
        elif flow == 'comment':
            with get_db() as db:
                card_id = db.execute(insert(Card).values(author_id=2, titulo='Bob',
                    capa='default-cover.svg', sobre='Review', nota=90).returning(Card.id)).scalar()
            path, data = f'/social/cards/{card_id}/comments', dict(body='A comment')
        else:
            path, data = '/backlog/add', dict(obra_id=1, status='completed')
    before = action_state(app)

    def change_account(db):
        # Introduce real database state after middleware authenticates the request,
        # at the boundary where a concurrent credential/account write can finish.
        if change == 'delete':
            db.execute(delete(User).where(User.id == 1))
        else:
            values = {'session_version': User.session_version + 1} if change == 'revoke' else (
                {'senha': 'a-new-credential-hash'} if change == 'password' else {'active': 0})
            db.execute(update(User).where(User.id == 1).values(**values))

    if flow == 'comment':
        original = social._lock_people

        def lock_after_change(first_id, second_id):
            change_account(get_db())
            return original(first_id, second_id)

        monkeypatch.setattr(social, '_lock_people', lock_after_change)
    else:
        original = backlog.lock_owner

        def lock_after_change(db, user_id):
            change_account(db)
            return original(db, user_id)

        monkeypatch.setattr(backlog, 'lock_owner', lock_after_change)

    headers = {'Accept': 'application/json'} if json_response else {}
    response = post(alice, path, data, headers=headers)
    assert response.status_code == status, response.text
    if json_response:
        assert response.get_json()['error']
    assert action_state(app) == before
