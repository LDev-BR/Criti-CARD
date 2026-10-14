"""Register with only access details, without weakening validation or legacy login."""
import re
from urllib.parse import parse_qs, urlsplit

import pytest

from conftest import image_file, post, rows
from criticard.db import get_db
from criticard.validation import email_valido


def access_details(**overrides):
    return {"username": "charlie", "email": "charlie@example.com", "senha": "Password1!", **overrides}


def test_registration_needs_only_access_details(client, app):
    result = post(client, "/cadastro", access_details())
    assert result.status_code == 302
    user = rows(app, "SELECT * FROM usuarios WHERE username='CHARLIE'")[0]
    assert user["nome"] == "CHARLIE"
    assert user["search_name"] == "charlie"
    assert user["apelido"] == "" and user["about"] == "" and user["imagem"] is None
    assert post(client, "/", {"username": "charlie@example.com", "senha": "Password1!"}).status_code == 302
    assert "CHARLIE" in client.get("/dashboard").text


def test_registration_keeps_optional_public_profile(client, app):
    result = post(client, "/cadastro", access_details(nome="Meu pseudônimo", apelido="Leitor",
        about="Gosto de boas histórias.", imagem=image_file()))
    assert result.status_code == 302
    user = rows(app, "SELECT * FROM usuarios WHERE username='CHARLIE'")[0]
    assert user["nome"] == "Meu pseudônimo" and user["apelido"] == "Leitor"
    assert user["about"] == "Gosto de boas histórias." and user["imagem"]


@pytest.mark.parametrize("email", ["a..b@example.com", ".alice@example.com", "alice@example..com",
    "alice@-example.com", "álice@example.com", "alice@example.com\0", "alice@exa_mple.com"])
def test_registration_rejects_malformed_email_before_persistence(client, app, email):
    result = post(client, "/cadastro", access_details(email=email, nome="Charlie", apelido="Leitor", about="Uma bio"))
    assert result.status_code == 200
    assert 'id="email-error"' in result.text and 'aria-invalid="true"' in result.text
    assert rows(app, "SELECT COUNT(*) FROM usuarios")[0][0] == 3


@pytest.mark.parametrize("email", ["a..b@example.com", "alice@-example.com", "álice@example.com", "alice@exa_mple.com"])
def test_email_validator_rejects_invalid_mailbox_syntax(email):
    assert not email_valido(email)


@pytest.mark.parametrize("email", ["reader+cards@example.com", "reader@no-mailbox-query-94327.com", "reader@exemplo.com.br"])
def test_email_validation_is_syntax_only(email):
    assert email_valido(email)


def test_login_keeps_existing_email_accepted_by_old_validator(client, app):
    with app.app_context():
        with get_db() as db:
            db.execute("UPDATE usuarios SET email=? WHERE id=1", ("old..address@example.com",))
    assert post(client, "/", {"username": "old..address@example.com", "senha": "Password1!"}).status_code == 302
    assert rows(app, "SELECT email FROM usuarios WHERE id=1")[0][0] == "old..address@example.com"


def test_signup_optional_fields_do_not_block_native_submission(client):
    page = client.get("/cadastro").text
    for field in ("nome", "apelido", "about"):
        tag = re.search(r'<(?:input|textarea)\b[^>]*\bid="' + field + r'"[^>]*>', page).group(0)
        assert "required" not in tag
    for field in ("username", "email", "senha"):
        assert "required" in re.search(r'<input\b[^>]*\bid="' + field + r'"[^>]*>', page).group(0)


def test_optional_profile_error_is_visible_after_server_validation(client):
    result = post(client, "/cadastro", access_details(nome="x" * 81))
    assert result.status_code == 200
    assert re.search(r'<details\b[^>]*\bopen(?:\s|>)', result.text)
    assert 'id="nome-error"' in result.text


def test_minimal_user_can_save_profile_without_adding_personal_details(client, app):
    assert post(client, "/cadastro", access_details()).status_code == 302
    assert post(client, "/", {"username": "charlie", "senha": "Password1!"}).status_code == 302
    result = post(client, "/edit", {"username": "charlie", "nome": "", "apelido": "",
        "about": "", "email": "charlie@example.com"})
    assert result.status_code == 302
    assert rows(app, "SELECT nome FROM usuarios WHERE username='CHARLIE'")[0][0] == "CHARLIE"


def test_edit_keeps_unchanged_legacy_email_without_forcing_an_address_change(alice, app):
    with app.app_context():
        with get_db() as db:
            db.execute("UPDATE usuarios SET email=? WHERE id=1", ("old..address@example.com",))
    result = post(alice, "/edit", {"username": "alice", "nome": "Um nome público", "apelido": "Leitor",
        "about": "Uma bio", "email": "old..address@example.com"})
    assert result.status_code == 302
    user = rows(app, "SELECT nome,email FROM usuarios WHERE id=1")[0]
    assert user["nome"] == "Um nome público" and user["email"] == "old..address@example.com"


def test_signup_explains_public_profile_and_links_to_privacy_policy(client):
    page = client.get("/cadastro").text
    assert re.search(r'<a\b[^>]*href="/privacidade"', page)
    assert "críticas são públicas" in page and "Email e senha ficam privados" in page


def test_registration_carries_requested_destination_back_to_login(client):
    result = post(client, "/cadastro", access_details(next="/cadastro_cards?obra_id=1"))
    assert result.status_code == 302
    location = urlsplit(result.location)
    assert location.path == "/"
    assert parse_qs(location.query)["next"] == ["/cadastro_cards?obra_id=1"]
    login_page = client.get(result.location).text
    destination = re.search(r'name="next" value="([^"]+)"', login_page).group(1)
    csrf = re.search(r'name="csrf_token" value="([^"]+)"', login_page).group(1)
    login = client.post("/", data={"username": "charlie", "senha": "Password1!",
        "next": destination, "csrf_token": csrf})
    assert login.status_code == 302 and login.location == "/cadastro_cards?obra_id=1"


def test_signup_keeps_destination_in_the_form_after_validation_error(client):
    result = post(client, "/cadastro", access_details(email="invalid", next="/privacidade/pedidos"))
    assert result.status_code == 200
    assert 'name="next" value="/privacidade/pedidos"' in result.text


@pytest.mark.parametrize("destination", ["https://outside.example/", "//outside.example/", "javascript:alert(1)"])
def test_signup_never_redirects_to_an_external_destination(client, destination):
    result = post(client, "/cadastro", access_details(next=destination))
    assert result.status_code == 302
    assert result.location == "/"
