"""Exercise account and publishing forms against an isolated live Flask server."""
import os
from urllib.parse import urlsplit

import pytest

from conftest import rows
from test_browser_reading import reading_page as form_page

pytestmark = pytest.mark.skipif(
    os.getenv("CRITICARD_BROWSER_TESTS") != "1",
    reason="Optional: install requirements-browser.txt and set CRITICARD_BROWSER_TESTS=1",
)


def origin(page):
    url = urlsplit(page.url)
    return f"{url.scheme}://{url.netloc}"


def sign_in(page):
    page.goto(origin(page) + "/")
    page.locator("#username").fill("alice@example.com")
    page.locator("#senha").fill("Password1!")
    page.locator(".form-submit").click()
    page.wait_for_url("**/dashboard")


def test_signup_password_controls_validation_and_real_account_creation(form_page, app):
    page = form_page
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(origin(page) + "/cadastro")
    page.locator(".form-submit").click()
    assert page.locator("#username").get_attribute("aria-invalid") == "true"
    assert page.locator("#username-error").is_visible()
    page.locator(".optional-profile > summary").click()
    page.locator("#nome").fill("Charlie")
    page.locator("#apelido").fill("Leitor")
    page.locator("#username").fill("charlie")
    page.locator("#about").fill("Histórias que ficam comigo.")
    page.locator("#email").fill("charlie@example.com")
    page.locator("#senha").fill("Password1!")
    assert page.locator('[data-rule][data-met="true"]').count() == 4
    page.locator("[data-password-toggle]").click()
    assert page.locator("#senha").get_attribute("type") == "text"
    assert page.locator("[data-password-toggle]").get_attribute("aria-pressed") == "true"
    page.locator("[data-password-toggle]").click()
    assert page.locator("#senha").get_attribute("type") == "password"
    assert page.locator("#about-count").inner_text() == "27/2000"
    page.locator(".form-submit").click()
    page.wait_for_url(origin(page) + "/")
    assert "Conta criada!" in page.locator(".flashes").inner_text()
    assert rows(app, "SELECT username FROM usuarios WHERE email='charlie@example.com'")[0][0] == "CHARLIE"
    assert not errors


def test_login_error_and_mobile_layout(form_page):
    page = form_page
    page.set_viewport_size({"width": 375, "height": 812})
    page.goto(origin(page) + "/")
    assert "Entrar" in page.title()
    page.locator("#username").fill("alice")
    page.locator("#senha").fill("wrong-password")
    page.locator(".form-submit").click()
    page.wait_for_load_state("networkidle")
    assert page.locator("[data-form-status]").is_visible()
    assert "Usuário ou senha inválidos" in page.locator("[data-form-status]").inner_text()
    assert page.locator("#username").input_value() == "alice"
    assert page.locator("#senha").input_value() == ""
    for route in ("/", "/cadastro"):
        page.goto(origin(page) + route)
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        for label in page.locator("label[for]").all():
            assert page.locator("#" + label.get_attribute("for")).count() == 1


def test_curated_preview_score_controls_publication_and_edit(form_page, app):
    page = form_page
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    sign_in(page)
    page.goto(origin(page) + "/cadastro_cards")
    page.locator("#categoria_id").select_option(label="Livros")
    page.locator("#obra_id").select_option(label="Duna")
    page.locator("#sobre").fill("Uma leitura memorável, com personagens inesquecíveis.")
    page.locator("#nota").fill("0")
    assert page.locator("[data-draft-title]").inner_text() == "Duna"
    assert page.locator("[data-draft-score]").inner_text() == "0"
    assert page.locator("[data-draft-excerpt]").inner_text().startswith("Uma leitura")
    assert page.locator("#titulo").get_attribute("readonly") is not None
    assert page.locator("input[type=file]").count() == 0
    assert page.locator("#cover-preview").get_attribute("src").endswith("/catalog/livros-atlas.png")
    page.locator('#nota-slider').focus()
    page.keyboard.press('End')
    assert page.locator('#nota').input_value() == '100'
    assert page.locator('[data-draft-score]').inner_text() == '100'
    page.locator('#nota').fill('101')
    page.locator('.form-submit').click()
    assert page.locator('#nota-error').is_visible()
    assert rows(app, 'SELECT COUNT(*) FROM cards')[0][0] == 1
    page.locator('#nota').fill('0')
    page.locator(".form-submit").click()
    page.wait_for_url("**/dashboard")
    card = rows(app, "SELECT * FROM cards WHERE id=2")[0]
    assert card["titulo"] == "Duna" and card["nota"] == 0
    page.goto(origin(page) + "/editar_card/2")
    assert page.locator("input[type=file]").count() == 0
    page.locator("#nota").fill("100")
    page.locator(".form-submit").click()
    page.wait_for_url("**/dashboard")
    edited = rows(app, "SELECT * FROM cards WHERE id=2")[0]
    assert edited["nota"] == 100 and edited["capa"] == card["capa"]
    assert not errors


def test_forms_remain_usable_without_javascript(form_page, app):
    page = form_page.context.browser.new_page(java_script_enabled=False, viewport={"width": 375, "height": 812})
    try:
        page.goto(origin(form_page) + "/")
        assert not page.locator("[data-password-toggle]").is_visible()
        sign_in(page)
        page.goto(origin(page) + "/cadastro_cards")
        assert "Criar card" in page.title()
        page.locator("#categoria_id").select_option(label="Livros")
        page.locator("#obra_id").select_option(label="1984")
        page.locator("#sobre").fill("O formulário também funciona com a validação do servidor.")
        page.locator("#nota").fill("80")
        assert page.locator("input[type=file]").count() == 0
        page.locator(".form-submit").click()
        page.wait_for_url("**/dashboard")
        assert rows(app, "SELECT titulo FROM cards WHERE id=2")[0][0] == "1984"
    finally:
        page.close()
