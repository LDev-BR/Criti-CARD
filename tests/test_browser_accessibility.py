"""Opt-in axe checks and account interactions against isolated data and local assets.

Install development tools with npm install, then set CRITICARD_BROWSER_TESTS=1.
The QA context bypasses CSP solely to inject axe; application CSP stays unchanged.
"""
import json
import os
from pathlib import Path
import tempfile

import pytest
from werkzeug.security import generate_password_hash

from criticard import create_app
from criticard.config import ROOT
from criticard.db import get_db
from test_browser_reading import reading_page as accessibility_page
from test_browser_forms import origin, sign_in
from test_chat import start, send, action

pytestmark = pytest.mark.skipif(os.getenv("CRITICARD_BROWSER_TESTS") != "1", reason="Optional browser accessibility checks")


@pytest.fixture
def app(tmp_path):
    app = create_app({"TESTING": True, "SECRET_KEY": "accessibility-test-key",
        "DATABASE": str(tmp_path / "accessibility.db"), "UPLOAD_FOLDER": str(tmp_path / "avatars"),
        "CAPA_FOLDER": str(tmp_path / "covers"), "ADM_USERNAME": "", "ADM_SENHA": "",
        "ACCOUNT_MAIL_BACKEND": "disabled", "ACCOUNT_SMTP_HOST": "", "ACCOUNT_SMTP_PASSWORD": ""})
    with app.app_context():
        with get_db() as db:
            for name in ("ALICE", "BOB", "ADMIN"):
                db.execute("INSERT INTO usuarios(username,nome,apelido,about,email,senha,admin) VALUES(?,?,?,?,?,?,?)",
                    (name, name.title(), "Leitor", "Boas histórias para compartilhar.", name.lower() + "@example.com",
                     generate_password_hash("Password1!"), int(name == "ADMIN")))
            db.execute("INSERT INTO cards(titulo,capa,sobre,nota,author_id) VALUES(?,?,?,?,?)",
                ("Uma história", "legacy.png", "Uma crítica completa.", 90, 1))
        from criticard.social.connections import change_friendship
        change_friendship(2, 1, "request")
    client, token, conversation = start(app)
    assert send(client, token, conversation, "Qual é sua próxima descoberta?").status_code == 201
    privacy_request = action(client, token, "/privacidade/pedidos", {"kind": "access", "body": "Quero saber mais sobre meus dados."})
    assert privacy_request.status_code == 201
    app.config["ACCESSIBILITY_PRIVACY_PROTOCOL"] = privacy_request.json["request"]["protocol"]
    app.config["ACCESSIBILITY_CONVERSATION"] = conversation
    yield app
    app.extensions["database_engine"].dispose()


def audit(page, artifact_dir, label):
    """Capture the rendered state before loading the development-only auditor."""
    from playwright.sync_api import expect
    page.evaluate("document.fonts.ready")
    # Full-page screenshots alone do not load offscreen lazy images. Visit all
    # catalogue items to verify the images a person sees while scrolling.
    for cover in page.locator('.catalog-grid .catalog-art-image').all():
        cover.scroll_into_view_if_needed()
        expect(cover).to_have_js_property('complete', True)
        assert cover.evaluate('img => img.naturalWidth > 0')
    page.evaluate('() => window.scrollTo(0, 0)')
    page.screenshot(path=str(artifact_dir / (label + ".png")), full_page=True)
    page.add_script_tag(path=str(ROOT / "node_modules" / "axe-core" / "axe.min.js"))
    result = page.evaluate("""async () => {
        const result = await axe.run(document, {runOnly: {type: 'tag', values:
            ['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa', 'best-practice']}});
        return result.violations.map(v => ({id:v.id, impact:v.impact,
            description:v.description, nodes:v.nodes.map(n => ({target:n.target, summary:n.failureSummary}))}));
    }""")
    return {"screen": label, "url": page.url, "violations": result}


def test_core_screens_and_mobile_have_no_axe_violations(accessibility_page, app):
    base = origin(accessibility_page)
    axe_path = ROOT / "node_modules" / "axe-core" / "axe.min.js"
    assert axe_path.exists(), "Run npm install to install the development-only axe auditor."
    artifacts = Path(tempfile.mkdtemp(prefix="criticard-accessibility-"))
    # The default browser fixture exercises normal CSP; only this audit context bypasses it.
    context = accessibility_page.context.browser.new_context(bypass_csp=True,
        viewport={"width": 1280, "height": 900}, reduced_motion="reduce")
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on("console", lambda message: errors.append(message.text) if message.type in ("error", "warning") else None)
    report = []
    try:
        for label, route in [("login", "/"), ("signup", "/cadastro"), ("guest-discovery", "/feed"),
            ("guest-reviews", "/criticas"), ("catalog", "/catalogo"),
            ("privacy-policy", "/privacidade")]:
            assert page.goto(base + route).status == 200
            assert page.title() and page.locator("main").inner_text().strip()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            report.append(audit(page, artifacts, label))
        page.goto(base + "/cadastro")
        page.locator(".optional-profile > summary").click()
        report.append(audit(page, artifacts, "signup-profile-expanded"))
        sign_in(page)
        conversation = app.config["ACCESSIBILITY_CONVERSATION"]
        protocol = app.config["ACCESSIBILITY_PRIVACY_PROTOCOL"]
        routes = [("dashboard", "/dashboard"), ("card-editor", "/cadastro_cards"),
            ("profile-edit", "/edit"), ("public-profile", "/perfil/BOB"), ("backlog", "/backlog"),
            ("requests", "/conexoes?aba=recebidas"), ("chat", f"/mensagens/{conversation}"),
            ("settings-account", "/configuracoes?secao=conta"),
            ("settings-appearance", "/configuracoes?secao=aparencia"),
            ("settings-privacy", "/configuracoes?secao=privacidade"),
            ("privacy-requests", "/privacidade/pedidos"), ("privacy-request-detail", f"/privacidade/pedidos/{protocol}")]
        for label, route in routes:
            assert page.goto(base + route).status == 200
            assert page.title() and page.locator("main").inner_text().strip()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            report.append(audit(page, artifacts, label))
        page.set_viewport_size({"width": 360, "height": 800})
        for label, route in [("catalog", "/catalogo"), ("requests", "/conexoes?aba=recebidas"),
            ("chat", f"/mensagens/{conversation}"), ("settings-account", "/configuracoes?secao=conta"),
            ("privacy-policy", "/privacidade"), ("privacy-requests", "/privacidade/pedidos"),
            ("privacy-request-detail", f"/privacidade/pedidos/{protocol}")]:
            assert page.goto(base + route).status == 200
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            report.append(audit(page, artifacts, label + "-mobile"))
        context.clear_cookies()
        page.goto(base + "/")
        page.locator("#username").fill("admin")
        page.locator("#senha").fill("Password1!")
        page.locator(".form-submit").click()
        page.wait_for_url(base + "/dashboard")
        for viewport in ({"width": 1280, "height": 900}, {"width": 360, "height": 800}):
            page.set_viewport_size(viewport)
            for label, route in [("privacy-admin", "/admin/privacidade"),
                ("privacy-admin-detail", f"/admin/privacidade/{protocol}")]:
                assert page.goto(base + route).status == 200
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                suffix = "-mobile" if viewport["width"] == 360 else ""
                report.append(audit(page, artifacts, label + suffix))
        (artifacts / "axe.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        violations = [entry for entry in report if entry["violations"]]
        print("Accessibility evidence:", artifacts)
        assert not errors, errors
        assert not violations, json.dumps(violations, ensure_ascii=False, indent=2)
    finally:
        context.close()


@pytest.mark.parametrize("javascript", [True, False])
def test_minimal_signup_is_usable_on_mobile_without_profile_or_javascript(accessibility_page, app, javascript):
    base = origin(accessibility_page)
    context = accessibility_page.context.browser.new_context(java_script_enabled=javascript,
        viewport={"width": 360, "height": 800})
    page = context.new_page()
    try:
        page.goto(base + "/cadastro")
        assert not page.locator(".optional-profile").evaluate("details => details.open")
        page.locator("#username").fill("charlie")
        page.locator("#email").fill("charlie@example.com")
        page.locator("#senha").fill("Password1!")
        page.locator(".form-submit").click()
        page.wait_for_url(base + "/")
        assert "Conta criada!" in page.locator(".flashes").inner_text()
        page.locator("#username").fill("charlie")
        page.locator("#senha").fill("Password1!")
        page.locator(".form-submit").click()
        page.wait_for_url(base + "/dashboard")
        assert page.locator("h1").inner_text() == "CHARLIE"
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    finally:
        context.close()


def test_closed_optional_profile_reopens_to_focus_an_invalid_upload(accessibility_page):
    from playwright.sync_api import expect
    page = accessibility_page
    page.goto(origin(page) + "/cadastro")
    page.locator("#username").fill("charlie")
    page.locator("#email").fill("charlie@example.com")
    page.locator("#senha").fill("Password1!")
    page.locator(".optional-profile > summary").click()
    page.locator("#imagem").set_input_files({"name": "too-large.png", "mimeType": "image/png",
        "buffer": b"x" * (3 * 1024 * 1024 + 1)})
    expect(page.locator("#imagem-error")).to_be_visible()
    page.locator(".optional-profile > summary").click()
    page.locator(".form-submit").click()
    expect(page.locator("#imagem-error")).to_be_visible()
    expect(page.locator("#imagem")).to_be_focused()


@pytest.mark.parametrize("javascript", [True, False])
def test_guest_signup_and_login_return_to_the_requested_private_screen(accessibility_page, javascript):
    base = origin(accessibility_page)
    context = accessibility_page.context.browser.new_context(java_script_enabled=javascript,
        viewport={"width": 360, "height": 800})
    page = context.new_page()
    try:
        page.goto(base + "/privacidade/pedidos")
        assert page.locator('input[name="next"]').input_value() == "/privacidade/pedidos"
        page.get_by_role("link", name="Crie sua conta", exact=True).click()
        page.locator("#username").fill("charlie")
        page.locator("#email").fill("charlie@example.com")
        page.locator("#senha").fill("Password1!")
        page.locator(".form-submit").click()
        page.wait_for_url(base + "/?next=**")
        page.locator("#username").fill("charlie")
        page.locator("#senha").fill("Password1!")
        page.locator(".form-submit").click()
        page.wait_for_url(base + "/privacidade/pedidos")
        assert page.get_by_role("heading", name="Pedidos sobre seus dados", exact=True).is_visible()
    finally:
        context.close()
