import io
import re

import pytest
from PIL import Image
from werkzeug.security import generate_password_hash

from criticard import create_app
from criticard.db import get_db


def image_file(filename="cover.png"):
    stream = io.BytesIO()
    Image.new("RGB", (12, 12), "gold").save(stream, format="PNG")
    stream.seek(0)
    return stream, filename


def post(client, url, data=None, **kwargs):
    # Exercise CSRF through the rendered form, not a test-only bypass.
    page = client.get("/", follow_redirects=True)
    token = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
    payload = dict(data or {})
    if url == "/cadastro_cards":
        # Older publication regressions supply a valid default catalog selection;
        # catalog-specific tests explicitly pass an empty or invalid obra_id.
        payload.setdefault("obra_id", "1")
    if token:
        payload["csrf_token"] = token.group(1)
    return client.post(url, data=payload, **kwargs)


@pytest.fixture
def app(tmp_path):
    config = {
        "TESTING": True,
        "SECRET_KEY": "integration-test-key",
        "DATABASE": str(tmp_path / "test.db"),
        "UPLOAD_FOLDER": str(tmp_path / "avatars"),
        "CAPA_FOLDER": str(tmp_path / "covers"),
    }
    application = create_app(config)
    with application.app_context():
        db = get_db()
        for username, email, admin in (
            ("ALICE", "alice@example.com", 0),
            ("BOB", "bob@example.com", 0),
            ("ADMIN", "admin@example.com", 1),
        ):
            db.execute(
                "INSERT INTO usuarios (username,nome,apelido,about,email,senha,admin) "
                "VALUES (?,?,?,?,?,?,?)",
                (username, username.title(), "Leitor", "Minha bio", email,
                 generate_password_hash("Password1!"), admin),
            )
        db.execute(
            "INSERT INTO cards (titulo,capa,sobre,nota,author_id) VALUES (?,?,?,?,?)",
            ("Card da Alice", "legacy.png", "Uma boa historia", 90, 1),
        )
        db.commit()
    yield application


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def alice(client):
    response = post(client, "/", {"username": "alice", "senha": "Password1!"})
    assert response.status_code == 302
    return client


def rows(app, query, params=()):
    with app.app_context():
        return get_db().execute(query, params).fetchall()
