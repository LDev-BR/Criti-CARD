"""Form errors must be actionable without losing the submitted draft."""
import io

from conftest import image_file, post, rows
from test_core import registration


def test_signup_identifies_invalid_field_and_keeps_nonsecret_values(client):
    payload = registration()
    payload["email"] = "invalid"
    response = post(client, "/cadastro", payload)
    assert 'id="email-error"' in response.text
    assert 'aria-invalid="true"' in response.text
    assert 'value="CHARLIE"' in response.text
    assert 'value="Password1!"' not in response.text


def test_signup_duplicate_email_identifies_email(client, app):
    payload = registration()
    payload["email"] = "ALICE@example.com"
    response = post(client, "/cadastro", payload)
    assert 'id="email-error"' in response.text
    assert "Email já cadastrado." in response.text
    assert rows(app, "SELECT COUNT(*) FROM usuarios")[0][0] == 3


def test_signup_password_policy_identifies_password(client):
    payload = registration()
    payload["senha"] = "short"
    response = post(client, "/cadastro", payload)
    assert 'id="senha-error"' in response.text
    assert 'value="short"' not in response.text


def test_card_invalid_score_keeps_draft_and_identifies_score(alice, app):
    response = post(alice, "/cadastro_cards", {"titulo": "Meu rascunho", "sobre": "Meu texto", "nota": "101"})
    assert 'id="nota-error"' in response.text
    assert 'value="Elden Ring"' in response.text
    assert "Meu texto" in response.text
    assert rows(app, "SELECT COUNT(*) FROM cards")[0][0] == 1


def test_catalog_invalid_file_identifies_cover(client, app):
    assert post(client, "/", {"username": "admin", "senha": "Password1!"}).status_code == 302
    response = post(client, "/admin/obras/nova", {"titulo": "Livro", "categoria_id": "1",
                    "capa": (io.BytesIO(b"bad image"), "cover.png")})
    assert response.status_code == 200
    assert 'id="capa-error"' in response.text
    assert "A imagem enviada é inválida." in response.text
    assert rows(app, "SELECT COUNT(*) FROM obras")[0][0] == 30


def padded_image(size):
    stream, filename = image_file()
    data = stream.getvalue()
    return io.BytesIO(data + b"\0" * (size - len(data))), filename


def test_image_at_size_limit_accepts_multipart_overhead_and_text(client, app):
    assert post(client, "/", {"username": "admin", "senha": "Password1!"}).status_code == 302
    response = post(client, "/admin/obras/nova", {"titulo": "No limite", "categoria_id": "1",
                    "descricao": "Crítica " * 200, "capa": padded_image(3 * 1024 * 1024)})
    assert response.status_code == 302
    assert rows(app, "SELECT titulo FROM obras WHERE id=31")[0][0] == "No limite"


def test_oversize_image_returns_inline_error_and_preserves_draft(client, app):
    assert post(client, "/", {"username": "admin", "senha": "Password1!"}).status_code == 302
    response = post(client, "/admin/obras/nova", {"titulo": "Meu rascunho", "categoria_id": "1",
                    "capa": padded_image(3 * 1024 * 1024 + 1)})
    assert response.status_code == 200
    assert 'id="capa-error"' in response.text and 'value="Meu rascunho"' in response.text
    assert "até 3 MB" in response.text
    assert rows(app, "SELECT COUNT(*) FROM obras")[0][0] == 30
