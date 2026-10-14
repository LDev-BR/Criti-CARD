"""Replacing a profile image retires only files without remaining references."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest
from sqlalchemy import insert, update

from conftest import image_file, post, rows
from criticard.db import get_db
from criticard.models import Card, User, Work
from test_privacy import member


@pytest.mark.parametrize('shared', [False, True])
def test_replacing_avatar_retires_old_file_without_deleting_another_profiles_image(app, shared):
    old = Path(app.config['UPLOAD_FOLDER']) / 'old-avatar.png'
    old.write_bytes(b'fixture image')
    with app.app_context():
        db = get_db()
        with db:
            db.execute(update(User).where(User.id.in_((1, 2) if shared else (1,))).values(imagem=old.name))
    client, _ = member(app)
    response = post(client, '/edit', {'username': 'ALICE', 'nome': 'Alice', 'apelido': 'Leitor',
        'about': 'Bio', 'email': 'alice@example.com', 'imagem': image_file()})
    assert response.status_code == 302
    current = rows(app, 'SELECT imagem FROM usuarios WHERE id=1')[0]['imagem']
    assert current != old.name and (Path(app.config['UPLOAD_FOLDER']) / current).exists()
    assert old.exists() is shared
    assert post(client, '/excluir_user', {'senha': 'Password1!'}).status_code == 302
    assert old.exists() is shared


def test_avatar_retirement_failure_is_retryable_after_profile_update_commits(app, monkeypatch):
    from criticard.storage import LocalStorage
    old = Path(app.config['UPLOAD_FOLDER']) / 'old-avatar.png'
    old.write_bytes(b'fixture image')
    with app.app_context():
        db = get_db()
        with db:
            db.execute(update(User).where(User.id == 1).values(imagem=old.name))
    def unavailable(_storage, _filename):
        raise OSError('Storage unavailable')
    monkeypatch.setattr(LocalStorage, 'remove', unavailable)
    client, _ = member(app)
    response = post(client, '/edit', {'username': 'ALICE', 'nome': 'Alice', 'apelido': 'Leitor',
        'about': 'Bio', 'email': 'alice@example.com', 'imagem': image_file()})
    assert response.status_code == 302
    assert rows(app, 'SELECT imagem FROM usuarios WHERE id=1')[0]['imagem'] != old.name
    assert old.exists()
    assert rows(app, 'SELECT filename FROM pending_image_deletions') == [{'filename': old.name}]
    monkeypatch.undo()
    result = app.test_cli_runner().invoke(args=['privacy-cleanup-images'])
    assert result.exit_code == 0 and not old.exists()
    assert rows(app, 'SELECT filename FROM pending_image_deletions') == []


def test_legacy_catalog_cover_reference_prevents_file_deletion(app):
    from criticard.privacy.cleanup import cleanup_images, queue_image
    filename = 'legacy.png'
    cover = Path(app.config['CAPA_FOLDER']) / filename
    cover.write_bytes(b'fixture image')
    with app.app_context():
        db = get_db()
        with db:
            db.execute('DELETE FROM cards WHERE id=1')
            db.execute(update(Work).where(Work.id == 1).values(capa='cards/' + filename))
            queue_image('cover', filename)
        assert cleanup_images()['failed'] == 0
    assert cover.exists()
    assert rows(app, 'SELECT filename FROM pending_image_deletions') == []


def test_shared_upload_and_cover_folder_preserves_catalog_alias_for_avatar_retirement(app):
    from criticard.privacy.cleanup import cleanup_images, queue_image
    app.config['UPLOAD_FOLDER'] = app.config['CAPA_FOLDER']
    filename = 'shared-kind.png'
    cover = Path(app.config['CAPA_FOLDER']) / filename
    cover.write_bytes(b'fixture image')
    with app.app_context():
        db = get_db()
        with db:
            db.execute(update(Work).where(Work.id == 1).values(capa='cards/' + filename))
            queue_image('avatar', filename)
        assert cleanup_images()['failed'] == 0
    assert cover.exists()


def test_concurrent_avatar_replacements_retire_the_actual_previous_file(app):
    from flask import request
    old = Path(app.config['UPLOAD_FOLDER']) / 'old-avatar.png'
    old.write_bytes(b'fixture image')
    with app.app_context():
        db = get_db()
        with db:
            db.execute(update(User).where(User.id == 1).values(imagem=old.name))
    sessions = [member(app), member(app)]
    barrier = Barrier(2)
    def synchronize_snapshots():
        if request.path == '/edit' and request.method == 'POST':
            barrier.wait(timeout=10)
    app.before_request_funcs[None].append(synchronize_snapshots)
    def replace(session):
        client, token = session
        return client.post('/edit', data={'username': 'ALICE', 'nome': 'Alice', 'apelido': 'Leitor',
            'about': 'Bio', 'email': 'alice@example.com', 'imagem': image_file(), 'csrf_token': token}).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(replace, sessions)) == [302, 302]
    current = rows(app, 'SELECT imagem FROM usuarios WHERE id=1')[0]['imagem']
    assert [path.name for path in Path(app.config['UPLOAD_FOLDER']).iterdir()] == [current]
    assert rows(app, 'SELECT filename FROM pending_image_deletions') == []


@pytest.mark.parametrize('marker', ['catalog-static:cards/legacy.png', 'catalog-static:legacy.png'])
def test_catalog_static_marker_on_other_card_preserves_shared_cover_after_erasure(app, marker):
    cover = Path(app.config['CAPA_FOLDER']) / 'legacy.png'
    cover.write_bytes(b'fixture image')
    with app.app_context():
        db = get_db()
        with db:
            db.execute(insert(Card).values(author_id=2, titulo='Card que usa a imagem', capa=marker,
                sobre='Outro participante', nota=90))
    client, _ = member(app)
    assert post(client, '/excluir_user', {'senha': 'Password1!'}).status_code == 302
    assert cover.exists()
    assert rows(app, 'SELECT capa FROM cards') == [{'capa': marker}]
