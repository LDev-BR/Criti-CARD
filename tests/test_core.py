import io
import sqlite3
from pathlib import Path

import pytest

from criticard import create_app
from criticard.db import get_db
from conftest import image_file, post, rows


def registration(**overrides):
    return dict(username="charlie", nome="Charlie", apelido="Leitor",
                about="Livros e jogos", email="charlie@example.com",
                senha="Password1!", **overrides)


def test_factory_initializes_without_admin_credentials(tmp_path, monkeypatch):
    monkeypatch.delenv("ADM_USERNAME", raising=False)
    monkeypatch.delenv("ADM_SENHA", raising=False)
    factory = create_app
    assert callable(factory), "A inicializacao deve estar disponivel na fabrica"
    application = factory({"TESTING": True, "SECRET_KEY": "test",
                           "DATABASE": str(tmp_path / "fresh.db"),
                           "UPLOAD_FOLDER": str(tmp_path / "avatars"),
                           "CAPA_FOLDER": str(tmp_path / "covers")})
    assert application.test_client().get("/").status_code == 200
    assert Path(application.config["CAPA_FOLDER"]).is_dir()
    assert rows(application, "SELECT COUNT(*) FROM usuarios")[0][0] == 0


def test_register_without_optional_avatar(client, app):
    response = post(client, "/cadastro", registration())
    assert response.status_code == 302
    assert rows(app, "SELECT username FROM usuarios WHERE email=?",
                ("charlie@example.com",))[0][0] == "CHARLIE"


def test_missing_registration_fields_return_validation(client, app):
    response = post(client, "/cadastro", {})
    assert response.status_code == 200
    assert rows(app, "SELECT COUNT(*) FROM usuarios")[0][0] == 3


def test_invalid_profile_edit_keeps_user_context(alice):
    response = post(alice, "/edit", {"username": "?", "nome": "Alice",
                    "apelido": "Leitor", "about": "Bio", "email": "alice@example.com",
                    "imagem": (io.BytesIO(), "")})
    assert response.status_code == 200
    assert "alice@example.com" in response.text


def test_email_edit_is_normalized_for_login(alice, app):
    response = post(alice, "/edit", {"username": "alice", "nome": "Alice",
                    "apelido": "Leitor", "about": "Bio", "email": "NEW@EXAMPLE.COM",
                    "imagem": (io.BytesIO(), "")})
    assert response.status_code == 302
    assert rows(app, "SELECT email FROM usuarios WHERE id=1")[0][0] == "new@example.com"


def test_login_does_not_store_password_hash(alice):
    with alice.session_transaction() as session:
        assert "user_senha" not in session


def test_logout_clears_entire_session(alice):
    response = post(alice, "/logout")
    assert response.status_code == 302
    with alice.session_transaction() as session:
        assert "usuario_id" not in session
        assert "user_admin" not in session
        assert "user_nome" not in session


def test_stale_session_redirects_to_login(client):
    with client.session_transaction() as session:
        session["usuario_id"] = 99999
    response = client.get("/dashboard")
    assert response.status_code == 302


def test_card_delete_get_is_read_only(alice, app):
    assert alice.get("/deletar_card/1").status_code == 405
    assert rows(app, "SELECT COUNT(*) FROM cards WHERE id=1")[0][0] == 1


def test_other_user_cannot_delete_card(client, app):
    post(client, "/", {"username": "bob", "senha": "Password1!"})
    assert post(client, "/deletar_card/1").status_code == 403
    assert rows(app, "SELECT COUNT(*) FROM cards WHERE id=1")[0][0] == 1


def test_author_can_delete_card(alice, app):
    assert post(alice, "/deletar_card/1").status_code == 302
    assert rows(app, "SELECT COUNT(*) FROM cards WHERE id=1")[0][0] == 0


@pytest.mark.parametrize("score", ["-1", "101", "7.5", "oops", ""])
def test_invalid_score_cannot_create_card(alice, app, score):
    response = post(alice, "/cadastro_cards", {"titulo": "Invalid score",
                    "sobre": "Uma critica", "nota": score, "capa": image_file()})
    assert response.status_code == 200
    assert rows(app, "SELECT COUNT(*) FROM cards")[0][0] == 1
    assert list(Path(app.config["CAPA_FOLDER"]).iterdir()) == []


def test_invalid_cover_cannot_create_catalog_work(client, app):
    assert post(client, "/", {"username": "admin", "senha": "Password1!"}).status_code == 302
    response = post(client, "/admin/obras/nova", {"titulo": "Invalid image",
                    "categoria_id": "1",
                    "capa": (io.BytesIO(b"not an image"), "photo.png")})
    assert response.status_code == 200
    assert rows(app, "SELECT COUNT(*) FROM obras")[0][0] == 30
    assert list(Path(app.config["CAPA_FOLDER"]).iterdir()) == []


def test_same_filename_does_not_overwrite_other_catalog_images(client, app):
    assert post(client, "/", {"username": "admin", "senha": "Password1!"}).status_code == 302
    for title in ("First", "Second"):
        response = post(client, "/admin/obras/nova", {"titulo": title,
                        "categoria_id": "1", "capa": image_file()})
        assert response.status_code == 302
    covers = rows(app, "SELECT capa FROM obras WHERE id>30 ORDER BY id")
    assert covers[0][0] != covers[1][0]
    assert len(list(Path(app.config["CAPA_FOLDER"]).iterdir())) == 2


def test_user_content_is_escaped(alice, app):
    with app.app_context():
        db = get_db()
        db.execute("UPDATE usuarios SET about=? WHERE id=1", ("<script>alert(1)</script>",))
        db.execute("UPDATE cards SET sobre=? WHERE id=1", ("<img src=x onerror=alert(1)>",))
        db.commit()
    response = alice.get("/dashboard")
    assert "<script>alert(1)</script>" not in response.text
    assert "<img src=x onerror=alert(1)>" not in response.text
    assert "&lt;script&gt;" in response.text


def test_mutations_require_csrf_token(client, app):
    payload = registration()
    payload["imagem"] = (io.BytesIO(), "")
    assert client.post("/cadastro", data=payload).status_code == 400
    assert rows(app, "SELECT COUNT(*) FROM usuarios")[0][0] == 3


def test_contact_requires_login(client):
    assert client.get("/mensagem").status_code == 302


def test_account_deletion_clears_session_and_cards(alice, app):
    response = post(alice, "/excluir_user", {"username": "alice", "senha": "Password1!"})
    assert response.status_code == 302
    assert rows(app, "SELECT COUNT(*) FROM usuarios WHERE id=1")[0][0] == 0
    assert rows(app, "SELECT COUNT(*) FROM cards WHERE author_id=1")[0][0] == 0
    with alice.session_transaction() as session:
        assert "usuario_id" not in session


def test_regular_user_cannot_access_admin(alice):
    response = alice.get("/listar_users")
    assert response.status_code == 403


def test_unicode_csrf_token_is_rejected_without_server_error(client):
    client.get("/")
    response = client.post("/cadastro", data={"csrf_token": "inválido"})
    assert response.status_code == 400


def test_legacy_session_password_hash_is_removed(alice):
    with alice.session_transaction() as session:
        session["user_senha"] = "legacy-password-hash"
        session["user_admin"] = 1
    response = alice.get("/dashboard")
    assert response.status_code == 200
    with alice.session_transaction() as session:
        assert "user_senha" not in session
        assert "user_admin" not in session


def test_cookie_admin_flag_does_not_grant_permission(alice):
    with alice.session_transaction() as session:
        session["user_admin"] = 1
    assert alice.get("/listar_users").status_code == 403


def test_duplicate_registration_does_not_save_avatar(client, app):
    payload = registration()
    payload["username"] = "alice"
    payload["imagem"] = image_file()
    assert post(client, "/cadastro", payload).status_code == 200
    assert rows(app, "SELECT COUNT(*) FROM usuarios")[0][0] == 3
    assert list(Path(app.config["UPLOAD_FOLDER"]).iterdir()) == []


def test_invalid_avatar_does_not_create_account(client, app):
    payload = registration()
    payload["imagem"] = (io.BytesIO(b"bad file"), "avatar.png")
    assert post(client, "/cadastro", payload).status_code == 200
    assert rows(app, "SELECT COUNT(*) FROM usuarios")[0][0] == 3


def test_cover_defaults_to_catalog_art(alice, app):
    assert post(alice, "/cadastro_cards", {"titulo": "Book", "sobre": "Review", "nota": "0"}).status_code == 302
    assert rows(app, "SELECT capa FROM cards WHERE id=2")[0][0] == 'catalog:jogos:0'


@pytest.mark.parametrize("score", ["0", "100"])
def test_score_boundaries_are_accepted(alice, app, score):
    assert post(alice, "/cadastro_cards", {"titulo": "Book", "sobre": "Review", "nota": score,
                                         "capa": image_file()}).status_code == 302
    assert rows(app, "SELECT nota FROM cards WHERE id=2")[0][0] == int(score)


def test_admin_requires_own_password_for_deletion(client, app):
    post(client, "/", {"username": "admin", "senha": "Password1!"})
    assert client.get("/listar_users").status_code == 200
    response = post(client, "/admin_excluir", {"username": "alice", "senha": "wrong"})
    assert response.status_code == 200
    assert rows(app, "SELECT COUNT(*) FROM usuarios WHERE id=1")[0][0] == 1
    assert post(client, "/admin_excluir", {"username": "alice", "senha": "Password1!"}).status_code == 302
    assert rows(app, "SELECT COUNT(*) FROM usuarios WHERE id=1")[0][0] == 0
    assert rows(app, "SELECT COUNT(*) FROM cards WHERE author_id=1")[0][0] == 0


def test_support_uses_authenticated_identity(alice, app):
    assert post(alice, "/mensagem", {"nome": "Other", "email": "spoof@example.com",
                                     "mensagem": "Preciso de ajuda"}).status_code == 302
    message = rows(app, "SELECT * FROM contatos")[0]
    assert message["nome"] == "ALICE" and message["email"] == "alice@example.com"


def test_existing_database_is_preserved_on_repeated_startup(tmp_path):
    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as db:
        db.executescript('''
            CREATE TABLE usuarios (id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL,
                nome TEXT NOT NULL, apelido TEXT NOT NULL, imagem TEXT, about TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL, senha TEXT NOT NULL, admin INTEGER DEFAULT 0);
            CREATE TABLE cards (id INTEGER PRIMARY KEY, titulo TEXT NOT NULL, capa TEXT NOT NULL,
                sobre TEXT NOT NULL, nota INTEGER NOT NULL, card_id INTEGER NOT NULL,
                FOREIGN KEY (card_id) REFERENCES usuarios(id));
            INSERT INTO usuarios VALUES (42,'LEGACY','Legacy','Leitor',NULL,'Bio','old@example.com','old-hash',0);
            INSERT INTO cards VALUES (7,'Old review','old.png','Review',80,42);
        ''')
    config = {"TESTING": True, "SECRET_KEY": "test", "DATABASE": str(path),
              "UPLOAD_FOLDER": str(tmp_path / "avatars"), "CAPA_FOLDER": str(tmp_path / "covers")}
    for _ in range(2):
        application = create_app(config)
        assert rows(application, "SELECT titulo FROM cards WHERE id=7")[0][0] == "Old review"
        assert "Old review" in application.test_client().get("/perfil/LEGACY").text


def test_dotenv_is_loaded_before_configuration(tmp_path, monkeypatch):
    from criticard import config
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.setattr(config, "ROOT", tmp_path)
    (tmp_path / ".env").write_text("SECRET_KEY=dotenv-test-key\n", encoding="utf-8")
    application = create_app({"TESTING": True, "DATABASE": str(tmp_path / "env.db"),
                              "UPLOAD_FOLDER": str(tmp_path / "avatars"),
                              "CAPA_FOLDER": str(tmp_path / "covers")})
    assert application.config["SECRET_KEY"] == "dotenv-test-key"
    monkeypatch.delenv("SECRET_KEY", raising=False)


def test_legacy_long_password_can_login_and_confirm_deletion(client, app):
    from werkzeug.security import generate_password_hash
    password = "Password1!" + "a" * 120
    with app.app_context():
        db = get_db()
        with db:
            db.execute("UPDATE usuarios SET senha=? WHERE id=1", (generate_password_hash(password),))
    assert post(client, "/", {"username": "alice", "senha": password}).status_code == 302
    with client.session_transaction() as session:
        assert session["usuario_id"] == 1
    assert post(client, "/excluir_user", {"senha": password}).status_code == 302
    assert rows(app, "SELECT COUNT(*) FROM usuarios WHERE id=1")[0][0] == 0


def test_invalid_support_message_preserves_text(alice):
    text = "Mensagem " + "a" * 2000
    response = post(alice, "/mensagem", {"mensagem": text}, follow_redirects=True)
    assert response.status_code == 200
    assert text in response.text
