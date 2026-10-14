"""Cards use curated work covers while preserving historical image references."""
import io
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from criticard.db import get_db
from conftest import image_file, post, rows


def work(app, title):
    return rows(app, "SELECT id,categoria_id FROM obras WHERE titulo=?", (title,))[0]


def publish(client, app, title, **extra):
    selected = work(app, title)
    payload = {"obra_id": str(selected["id"]), "categoria_id": str(selected["categoria_id"]),
               "sobre": "Uma experiência que merece ser compartilhada.", "nota": "85"}
    payload.update(extra)
    return post(client, "/cadastro_cards", payload)


def test_publish_with_catalog_art_without_upload(alice, app):
    assert publish(alice, app, "Elden Ring").status_code == 302
    card = rows(app, "SELECT * FROM cards WHERE id=2")[0]
    assert card["capa"] == "catalog:jogos:0"
    assert "catalog/jogos-atlas.png" in alice.get("/card/2").text


@pytest.mark.parametrize("valid_image", [True, False])
def test_author_upload_cannot_replace_catalog_cover(alice, app, valid_image):
    uploaded = image_file() if valid_image else (io.BytesIO(b"not an image"), "cover.png")
    assert publish(alice, app, "Elden Ring", capa=uploaded).status_code == 302
    assert rows(app, "SELECT capa FROM cards WHERE id=2")[0][0] == "catalog:jogos:0"
    assert list(Path(app.config["CAPA_FOLDER"]).iterdir()) == []


def test_edit_work_changes_curated_cover_and_ignores_author_upload(alice, app):
    assert publish(alice, app, "Elden Ring").status_code == 302
    selected = work(app, "Hades")
    payload = {"obra_id": str(selected["id"]), "categoria_id": str(selected["categoria_id"]),
               "sobre": "Uma nova opinião.", "nota": "90"}
    assert post(alice, "/editar_card/2", payload).status_code == 302
    assert rows(app, "SELECT capa FROM cards WHERE id=2")[0][0] == "catalog:jogos:3"
    assert post(alice, "/editar_card/2", {**payload, "nota": "95", "capa": image_file()}).status_code == 302
    assert rows(app, "SELECT capa,nota FROM cards WHERE id=2")[0] == {
        "capa": "catalog:jogos:3", "nota": 95}
    assert rows(app, "SELECT COUNT(*) FROM cards")[0][0] == 2
    assert list(Path(app.config["CAPA_FOLDER"]).iterdir()) == []


def test_client_cannot_choose_arbitrary_art_marker(alice, app):
    assert publish(alice, app, "Elden Ring", catalog_cover="../../secret_key").status_code == 302
    assert rows(app, "SELECT capa FROM cards WHERE id=2")[0][0] == "catalog:jogos:0"


def test_custom_catalog_image_is_reused_in_preview_and_publication(alice, app, tmp_path):
    assets = tmp_path / 'static'
    assets.mkdir()
    (assets / 'custom-work.webp').write_bytes(b'fixture image')
    app.static_folder = str(assets)
    with app.app_context():
        with get_db() as db:
            db.execute("UPDATE obras SET capa=? WHERE titulo='Duna'", ('custom-work.webp',))
    assert 'data-cover-source="/static/custom-work.webp"' in alice.get('/cadastro_cards').text
    assert publish(alice, app, 'Duna').status_code == 302
    assert rows(app, 'SELECT capa FROM cards WHERE id=2')[0][0] == 'catalog-static:custom-work.webp'
    assert 'src="/static/custom-work.webp"' in alice.get('/card/2').text


def historical_cover(app, filename='legacy.png'):
    path = Path(app.config['CAPA_FOLDER']) / filename
    stream, _ = image_file()
    path.write_bytes(stream.getvalue())
    return path


def test_deleting_historical_card_removes_unreferenced_cover(alice, app):
    path = historical_cover(app)
    assert post(alice, '/deletar_card/1').status_code == 302
    assert not path.exists()
    assert rows(app, 'SELECT filename FROM pending_image_deletions') == []


def test_deleting_historical_card_preserves_cover_shared_by_another_card(alice, app):
    path = historical_cover(app)
    with app.app_context():
        with get_db() as db:
            db.execute('INSERT INTO cards (titulo,capa,sobre,nota,author_id) VALUES (?,?,?,?,?)',
                ('Outro histórico', path.name, 'Texto preservado', 80, 2))
    assert post(alice, '/deletar_card/1').status_code == 302
    assert path.is_file()
    assert rows(app, 'SELECT capa FROM cards WHERE id=2')[0][0] == path.name


def test_deleting_card_preserves_cover_used_by_catalog(alice, app):
    path = historical_cover(app)
    with app.app_context():
        with get_db() as db:
            db.execute('UPDATE obras SET capa=? WHERE id=1', (path.name,))
    assert post(alice, '/deletar_card/1').status_code == 302
    assert path.is_file()


def test_linking_historical_card_to_work_retires_its_unreferenced_cover(alice, app):
    old = historical_cover(app)
    selected = work(app, 'Duna')
    assert post(alice, '/editar_card/1', {'obra_id': str(selected['id']), 'sobre': 'Atualizada',
        'nota': '80', 'capa': image_file()}).status_code == 302
    assert not old.exists()
    assert rows(app, 'SELECT capa FROM cards WHERE id=1')[0][0] == 'catalog:livros:1'
    assert list(Path(app.config['CAPA_FOLDER']).iterdir()) == []


def test_concurrent_historical_edits_ignore_uploads_and_preserve_existing_cover(app, monkeypatch):
    from flask import request
    from criticard import cards
    from test_privacy import member
    sessions = [member(app), member(app)]
    historical_cover(app)
    barrier = Barrier(2)
    lookup = cards.get_card
    def snapshots(id):
        card = lookup(id)
        if request.method == 'POST':
            barrier.wait(timeout=10)
        return card
    monkeypatch.setattr(cards, 'get_card', snapshots)
    def edit(session):
        client, token = session
        return client.post('/editar_card/1', data={'sobre': 'Atualizada', 'nota': '80',
            'titulo': 'Card atualizado', 'capa': image_file(), 'csrf_token': token}).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(edit, sessions)) == [302, 302]
    current = rows(app, 'SELECT capa FROM cards WHERE id=1')[0][0]
    assert current == 'legacy.png'
    assert [path.name for path in Path(app.config['CAPA_FOLDER']).iterdir()] == [current]
    assert rows(app, 'SELECT filename FROM pending_image_deletions') == []


def test_revoked_session_cannot_publish_or_leave_an_uploaded_image(app):
    from flask import request
    from test_privacy import member
    client, token = member(app)
    def revoke_after_load():
        if request.path == '/cadastro_cards' and request.method == 'POST':
            with get_db() as db:
                db.execute('UPDATE usuarios SET session_version=session_version+1 WHERE id=1')
    app.before_request_funcs[None].append(revoke_after_load)
    response = client.post('/cadastro_cards', data={'obra_id': '1', 'sobre': 'Crítica', 'nota': '80',
        'capa': image_file(), 'csrf_token': token})
    assert response.status_code == 401
    assert rows(app, 'SELECT COUNT(*) FROM cards')[0][0] == 1
    assert list(Path(app.config['CAPA_FOLDER']).iterdir()) == []


def test_text_edit_uses_catalog_cover_updated_before_author_lock(alice, app, monkeypatch):
    from criticard import cards
    from test_privacy import member
    assert publish(alice, app, 'Elden Ring').status_code == 302
    administrator, token = member(app, 3)
    original = cards._lock_author
    def update_catalog_before_lock(db):
        def save_curated_cover():
            return administrator.post('/admin/obras/1/editar', data={'titulo': 'Elden Ring',
                'categoria_id': '1', 'capa': image_file(), 'csrf_token': token}).status_code
        with ThreadPoolExecutor(max_workers=1) as pool:
            assert pool.submit(save_curated_cover).result(timeout=10) == 302
        return original(db)
    monkeypatch.setattr(cards, '_lock_author', update_catalog_before_lock)
    assert post(alice, '/editar_card/2', {'obra_id': '1', 'sobre': 'Texto atualizado', 'nota': '80'}).status_code == 302
    cover = rows(app, 'SELECT capa FROM cards WHERE id=2')[0][0]
    assert cover == rows(app, 'SELECT capa FROM obras WHERE id=1')[0][0]
    assert cover.endswith('.png')
    assert (Path(app.config['CAPA_FOLDER']) / cover).is_file()
