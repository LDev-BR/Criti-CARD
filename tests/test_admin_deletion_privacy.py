"""Administrative erasure must authorize fresh locked accounts, not snapshots."""
from flask import request
import pytest
from sqlalchemy import update
from werkzeug.security import generate_password_hash

from conftest import rows
from criticard.db import get_db
from criticard.models import User
from test_privacy import member


@pytest.mark.parametrize('changes', [
    {'admin': 0}, {'session_version': 1}, {'active': 0},
    {'senha': generate_password_hash('Changed2!')},
])
def test_admin_erasure_rechecks_revoked_role_session_activity_and_password(app, changes):
    client, token = member(app, 3)
    def change_after_user_loaded():
        if request.path == '/admin_excluir' and request.method == 'POST':
            db = get_db()
            with db:
                db.execute(update(User).where(User.id == 3).values(**changes))
    app.before_request_funcs[None].append(change_after_user_loaded)
    response = client.post('/admin_excluir', data={'username': 'alice', 'senha': 'Password1!', 'csrf_token': token})
    assert rows(app, 'SELECT id FROM usuarios WHERE id=1') == [{'id': 1}]
    assert response.status_code in (302, 403)
    if response.status_code == 302:
        assert response.location == '/'


def test_promoted_target_is_protected_when_identity_lookup_snapshot_is_stale(app, monkeypatch):
    from criticard import admin
    client, token = member(app, 3)
    lookup = admin.find_identity
    def promote_after_lookup(identity):
        snapshot = lookup(identity)
        db = get_db()
        with db:
            db.execute(update(User).where(User.id == snapshot['id']).values(admin=1))
        return snapshot
    monkeypatch.setattr(admin, 'find_identity', promote_after_lookup)
    response = client.post('/admin_excluir', data={'username': 'alice', 'senha': 'Password1!', 'csrf_token': token})
    assert response.status_code == 200
    assert rows(app, 'SELECT admin FROM usuarios WHERE id=1') == [{'admin': 1}]
    assert rows(app, 'SELECT id FROM cards WHERE author_id=1') == [{'id': 1}]


def test_admin_erasure_requires_csrf_and_uses_persistent_attempt_budget(app):
    app.config['SETTINGS_SECURITY_ATTEMPT_LIMIT'] = 1
    client, token = member(app, 3)
    data = {'username': 'alice', 'senha': 'Password1!'}
    assert client.post('/admin_excluir', data=data).status_code == 400
    assert client.post('/admin_excluir', data=dict(data, senha='wrong', csrf_token=token)).status_code == 200
    response = client.post('/admin_excluir', data=dict(data, csrf_token=token))
    assert response.status_code == 429 and int(response.headers['Retry-After']) > 0
    assert rows(app, 'SELECT id FROM usuarios WHERE id=1') == [{'id': 1}]


def test_admin_erasure_reports_pending_image_cleanup_after_account_deletion(app, monkeypatch):
    from pathlib import Path
    from criticard.storage import LocalStorage
    (Path(app.config['CAPA_FOLDER']) / 'legacy.png').write_bytes(b'fixture image')
    def unavailable(_storage, _filename):
        raise OSError('Storage unavailable')
    monkeypatch.setattr(LocalStorage, 'remove', unavailable)
    client, token = member(app, 3)
    response = client.post('/admin_excluir', data={'username': 'alice', 'senha': 'Password1!',
        'csrf_token': token}, follow_redirects=True)
    assert response.status_code == 200
    assert rows(app, 'SELECT id FROM usuarios WHERE id=1') == []
    assert rows(app, 'SELECT filename FROM pending_image_deletions') == [{'filename': 'legacy.png'}]
    assert 'remoção pendente' in response.text
