"""The collection is independent from reviews and private unless shared."""
import re
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import insert, select
from werkzeug.security import generate_password_hash

from criticard import create_app
from criticard.db import get_db
from criticard.models import Card, User, Work


@pytest.fixture
def backlog_app(tmp_path):
    app = create_app({
        "TESTING": True, "SECRET_KEY": "backlog-test-key",
        "DATABASE": str(tmp_path / "backlog.db"),
        "UPLOAD_FOLDER": str(tmp_path / "avatars"),
        "CAPA_FOLDER": str(tmp_path / "covers"),
        "ADM_USERNAME": "", "ADM_SENHA": "",
    })
    with app.app_context():
        db = get_db()
        with db:
            for name in ("ALICE", "BOB"):
                db.execute(insert(User).values(username=name, nome=name.title(), apelido="Leitor",
                           about="Minha coleção", email=name.lower() + "@example.com",
                           senha=generate_password_hash("Password1!"), search_name=name.lower()))
    yield app


@pytest.fixture
def backlog_client(backlog_app):
    return backlog_app.test_client()


def authenticate(client, user_id):
    from criticard.security import session_identity
    with client.application.app_context():
        user = get_db().execute(select(User).where(User.id == user_id)).fetchone()
        stamp = session_identity(user)
    with client.session_transaction() as session:
        session["usuario_id"] = user_id
        session["session_version"] = user["session_version"]
        session["auth_stamp"] = stamp


@pytest.fixture
def backlog_alice(backlog_client):
    authenticate(backlog_client, 1)
    return backlog_client


def api(client, path, data=None, *, csrf=True):
    page = client.get("/", follow_redirects=True)
    token = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
    headers = {"Accept": "application/json"}
    if csrf and token:
        headers["X-CSRF-Token"] = token.group(1)
    return client.post(path, json=data or {}, headers=headers)


def form_post(client, path, data=None):
    page = client.get("/", follow_redirects=True)
    token = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
    payload = dict(data or {})
    if token:
        payload["csrf_token"] = token.group(1)
    return client.post(path, data=payload)


def query(app, statement):
    with app.app_context():
        return get_db().execute(statement).fetchall()


def work_id(app, title):
    return query(app, select(Work.id).where(Work.titulo == title))[0][0]


def add(client, app, title="Berserk", **values):
    return api(client, "/backlog/add", {"obra_id": work_id(app, title), **values})


def items(app):
    return query(app, "SELECT * FROM backlog_items ORDER BY id")


def test_catalog_is_public_and_has_add_action_without_review_upload(backlog_client):
    response = backlog_client.get("/catalogo")
    assert response.status_code == 200
    assert "Berserk" in response.text and "Elden Ring" in response.text
    assert 'type="file"' not in response.text


def test_add_is_private_planned_and_does_not_create_a_review(backlog_alice, backlog_app):
    response = add(backlog_alice, backlog_app)
    assert response.status_code == 201
    assert response.json["created"] is True
    item = items(backlog_app)[0]
    assert item["user_id"] == 1
    assert item["status"] == "planned" and item["visibility"] == "private"
    assert item["progress"] is None and item["progress_unit"] is None
    assert query(backlog_app, select(Card.id)) == []


def test_adding_a_duplicate_keeps_one_item_and_preserves_progress(backlog_alice, backlog_app):
    first = add(backlog_alice, backlog_app, status="in_progress", progress=12, progress_unit="chapters")
    repeated = add(backlog_alice, backlog_app)
    assert first.status_code == 201 and repeated.status_code == 200
    assert repeated.json["created"] is False
    assert first.json["item"]["id"] == repeated.json["item"]["id"]
    assert len(items(backlog_app)) == 1
    assert items(backlog_app)[0]["progress"] == 12


@pytest.mark.parametrize("payload", [
    {"obra_id": "invalid"}, {"obra_id": 0}, {"obra_id": -1},
    {"obra_id": 999999}, {"obra_id": 2**63}, {"obra_id": True},
    {"obra_id": 1.5}, {"obra_id": "1", "status": "other"},
    {"obra_id": "1", "visibility": "friends"},
    {"obra_id": "1", "progress": -1}, {"obra_id": "1", "progress": 100001},
    {"obra_id": "1", "progress": "2.5"}, {"obra_id": "1", "progress": True},
    {"obra_id": "1", "progress_unit": "pages"},
])
def test_invalid_input_does_not_create_item(backlog_alice, backlog_app, payload):
    response = api(backlog_alice, "/backlog/add", payload)
    assert response.status_code == (404 if payload["obra_id"] == 999999 else 422)
    assert response.is_json and response.json.get("error")
    assert items(backlog_app) == []


def test_backlog_requires_authentication_and_csrf(backlog_client, backlog_app):
    response = api(backlog_client, "/backlog/add", {"obra_id": 1})
    assert response.status_code == 401
    assert response.is_json
    assert backlog_client.get("/backlog").status_code == 302
    authenticate(backlog_client, 1)
    response = api(backlog_client, "/backlog/add", {"obra_id": 1}, csrf=False)
    assert response.status_code in (400, 403)
    assert items(backlog_app) == []


def test_item_owner_can_update_clear_progress_and_remove(backlog_alice, backlog_app):
    item_id = add(backlog_alice, backlog_app).json["item"]["id"]
    response = api(backlog_alice, f"/backlog/{item_id}/update",
                   {"status": "completed", "visibility": "public", "progress": 0, "progress_unit": "chapters"})
    assert response.status_code == 200
    item = items(backlog_app)[0]
    assert item["status"] == "completed" and item["visibility"] == "public"
    assert item["progress"] == 0 and item["progress_unit"] == "chapters"
    assert api(backlog_alice, f"/backlog/{item_id}/update", {"progress": "", "progress_unit": ""}).status_code == 200
    assert items(backlog_app)[0]["progress"] is None
    assert api(backlog_alice, f"/backlog/{item_id}/remove").status_code == 200
    assert items(backlog_app) == []


def test_other_users_cannot_update_or_remove_an_item(backlog_alice, backlog_app):
    item_id = add(backlog_alice, backlog_app).json["item"]["id"]
    authenticate(backlog_alice, 2)
    assert api(backlog_alice, f"/backlog/{item_id}/update", {"visibility": "public"}).status_code == 404
    assert api(backlog_alice, f"/backlog/{item_id}/remove").status_code == 404
    assert items(backlog_app)[0]["visibility"] == "private"


def test_public_collection_hides_private_items_from_guests_and_other_users(backlog_alice, backlog_app):
    add(backlog_alice, backlog_app, "Berserk")
    add(backlog_alice, backlog_app, "Duna", visibility="public")
    owner = backlog_alice.get("/colecao/alice")
    assert owner.status_code == 200 and "Berserk" in owner.text and "Duna" in owner.text
    guest = backlog_app.test_client().get("/colecao/alice")
    assert guest.status_code == 200 and "Duna" in guest.text and "Berserk" not in guest.text
    assert "2 obras" not in guest.text
    authenticate(backlog_alice, 2)
    other = backlog_alice.get("/colecao/ALICE")
    assert "Duna" in other.text and "Berserk" not in other.text
    assert 'data-backlog-update' not in other.text


def test_unknown_collection_returns_404(backlog_client):
    assert backlog_client.get("/colecao/naoexiste").status_code == 404


def test_filters_combine_status_category_and_case_insensitive_search(backlog_alice, backlog_app):
    add(backlog_alice, backlog_app, "Berserk", status="in_progress")
    add(backlog_alice, backlog_app, "Duna", status="completed")
    add(backlog_alice, backlog_app, "1984", status="in_progress")
    response = backlog_alice.get("/backlog?status=in_progress&categoria=livros&q=1984")
    assert response.status_code == 200
    assert "1984" in response.text and "Berserk" not in response.text and "Duna" not in response.text
    response = backlog_alice.get("/catalogo?categoria=mangas&q=BERsERK")
    assert "Berserk" in response.text and "Duna" not in response.text
    assert backlog_alice.get("/catalogo?q=%25").text.count('data-catalog-work') == 0


def test_forms_work_without_javascript_and_use_selected_work_for_review(backlog_alice, backlog_app):
    work = work_id(backlog_app, "Hades")
    response = form_post(backlog_alice, "/backlog/add", {"obra_id": work})
    assert response.status_code == 302 and response.location.endswith("/backlog")
    page = backlog_alice.get("/backlog")
    assert f"/cadastro_cards?obra_id={work}" in page.text
    assert "Quero jogar" in page.text
    assert 'name="csrf_token"' in page.text
    item_id = items(backlog_app)[0]["id"]
    assert form_post(backlog_alice, f"/backlog/{item_id}/update", {"status": "paused"}).status_code == 302
    assert items(backlog_app)[0]["status"] == "paused"
    assert form_post(backlog_alice, f"/backlog/{item_id}/remove").status_code == 302
    assert items(backlog_app) == []


def test_invalid_update_is_atomic_and_unknown_item_does_not_write(backlog_alice, backlog_app):
    item_id = add(backlog_alice, backlog_app).json["item"]["id"]
    assert api(backlog_alice, f"/backlog/{item_id}/update", {"visibility": "public", "progress": -1}).status_code == 422
    assert items(backlog_app)[0]["visibility"] == "private"
    assert api(backlog_alice, "/backlog/999999/update", {"status": "completed"}).status_code == 404


@pytest.mark.parametrize("field,value", [("status", []), ("visibility", {}), ("progress_unit", []), ("progress", {})])
def test_structured_values_are_validation_errors_not_server_errors(backlog_alice, backlog_app, field, value):
    response = add(backlog_alice, backlog_app, **{field: value})
    assert response.status_code == 422
    assert response.json["field"] == field
    assert items(backlog_app) == []


def test_simultaneous_additions_return_the_same_item(backlog_app):
    gate = Barrier(4)
    work = work_id(backlog_app, "Berserk")

    def request_add(_):
        client = backlog_app.test_client()
        authenticate(client, 1)
        with client.session_transaction() as session:
            session["csrf_token"] = "concurrent-backlog-token"
        gate.wait(timeout=10)
        response = client.post("/backlog/add", json={"obra_id": work},
                               headers={"X-CSRF-Token": "concurrent-backlog-token"})
        return response.status_code, response.json["item"]["id"]

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(request_add, range(4)))
    assert sorted(code for code, _ in results) == [200, 200, 200, 201]
    assert len({item_id for _, item_id in results}) == 1
    assert len(items(backlog_app)) == 1


def test_two_people_can_collect_the_same_work(backlog_alice, backlog_app):
    add(backlog_alice, backlog_app)
    authenticate(backlog_alice, 2)
    assert add(backlog_alice, backlog_app).status_code == 201
    assert [item["user_id"] for item in items(backlog_app)] == [1, 2]
    assert backlog_alice.get("/backlog").text.count('data-backlog-item=') == 1


def test_cover_uses_existing_local_asset_and_safe_fallback(backlog_alice, backlog_app, tmp_path):
    from sqlalchemy import update
    assets = tmp_path / "assets"
    (assets / "covers").mkdir(parents=True)
    (assets / "covers" / "berserk.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
    backlog_app.static_folder = str(assets)
    with backlog_app.app_context():
        db = get_db()
        with db:
            db.execute(update(Work).where(Work.titulo == "Berserk").values(capa="covers/berserk.svg"))
            db.execute(update(Work).where(Work.titulo == "Duna").values(capa="https://example.com/fake-cover.png"))
    response = backlog_alice.get("/catalogo")
    assert '/static/covers/berserk.svg' in response.text
    assert '/static/default-cover.svg' in response.text
    assert 'https://example.com/fake-cover.png' not in response.text


def test_non_image_asset_cannot_be_used_as_a_catalog_cover(backlog_alice, backlog_app):
    from sqlalchemy import update
    with backlog_app.app_context():
        db = get_db()
        with db:
            db.execute(update(Work).where(Work.titulo == "Berserk").values(capa="backlog.css"))
    page = backlog_alice.get("/catalogo?categoria=mangas&q=Berserk")
    assert '<img src="/static/backlog.css"' not in page.text
    assert '<img src="/static/default-cover.svg"' in page.text
