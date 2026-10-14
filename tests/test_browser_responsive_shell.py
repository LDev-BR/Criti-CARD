"""Responsive shell proof using an isolated database and fake catalogue only."""
import json
import os
import shutil
from threading import Thread

import pytest
from PIL import Image
from werkzeug.security import generate_password_hash
from werkzeug.serving import make_server

from criticard import create_app
from criticard.config import ROOT
from criticard.db import get_db

pytestmark = pytest.mark.skipif(os.getenv("CRITICARD_BROWSER_TESTS") != "1", reason="Optional browser QA")


@pytest.fixture
def responsive_browser(tmp_path):
    from playwright.sync_api import sync_playwright
    assets = tmp_path / "static"
    shutil.copytree(ROOT / "static", assets, ignore=shutil.ignore_patterns("uploads", "cards"))
    (assets / "cards").mkdir()
    (assets / "uploads").mkdir()
    Image.new("RGB", (320, 240), "#29251c").save(assets / "cards" / "fake.png")
    app = create_app({"TESTING": True, "SECRET_KEY": "responsive-fake-test-key",
        "DATABASE": str(tmp_path / "fake.db"), "UPLOAD_FOLDER": str(assets / "uploads"),
        "CAPA_FOLDER": str(assets / "cards"), "ADM_USERNAME": "", "ADM_SENHA": "",
        "ACCOUNT_MAIL_BACKEND": "disabled", "ACCOUNT_SMTP_HOST": "", "ACCOUNT_SMTP_PASSWORD": ""})
    app.static_folder = str(assets)
    with app.app_context():
        db = get_db()
        for username, name, admin in [("FAKEAUTHOR", "Pessoa fictícia", 0), ("FAKEFRIEND", "Amigo fictício", 0), ("FAKEADMIN", "Admin fictício", 1)]:
            db.execute("INSERT INTO usuarios(username,nome,apelido,about,email,senha,admin) VALUES(?,?,?,?,?,?,?)",
                (username, name, "Leitor", "Histórias para compartilhar.", username.lower() + "@example.test", generate_password_hash("Password1!"), admin))
        works = db.execute("SELECT id FROM obras ORDER BY id").fetchall()
        for index, work in enumerate(works, 1):
            title = f"História fictícia {index}"
            db.execute("UPDATE obras SET titulo=?,search_title=? WHERE id=?", (title, title.casefold(), work[0]))
        for index, work in enumerate(works[:6], 1):
            db.execute("INSERT INTO cards(titulo,capa,sobre,nota,author_id,obra_id) VALUES(?,?,?,?,?,?)",
                (f"Descoberta fictícia {index}", "fake.png", "Uma crítica completa para testar a leitura e os controles.", 85, 1, work[0]))
        db.commit()
        from criticard.social.connections import change_friendship
        change_friendship(2, 1, "request")
    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="msedge" if os.name == "nt" else None, headless=True)
            yield browser, f"http://127.0.0.1:{server.server_port}"
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        app.extensions["database_engine"].dispose()


def sign_in(page, base, username="fakeauthor"):
    page.goto(base + "/")
    page.locator("#username").fill(username)
    page.locator("#senha").fill("Password1!")
    page.locator(".form-submit").click()
    page.wait_for_url(base + "/dashboard")


GEOMETRY = """selector => {
    const r = document.querySelector(selector)?.getBoundingClientRect();
    const main = document.querySelector('main').getBoundingClientRect();
    return {viewport: innerHeight, width: innerWidth, scrollWidth: document.documentElement.scrollWidth,
      height: document.documentElement.scrollHeight, header: document.querySelector('.site-header').offsetHeight,
      footer: document.querySelector('.site-footer').offsetHeight, mainY: Math.round(main.top),
      contentY: r ? Math.round(r.top) : null, contentHeight: r ? Math.round(r.height) : null,
      firstViewport: r ? r.top < innerHeight : false};
}"""


def test_capture_responsive_geometry_and_axe(responsive_browser):
    browser, base = responsive_browser
    phase = os.getenv("CRITICARD_RESPONSIVE_PHASE", "after")
    artifacts = ROOT / ".runtime" / "responsive-qa" / phase
    artifacts.mkdir(parents=True, exist_ok=True)
    report, errors = [], []
    context = browser.new_context(bypass_csp=True, reduced_motion="reduce")
    page = context.new_page()
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on("console", lambda message: errors.append(message.text) if message.type in ("error", "warning") else None)
    try:
        for width, height in [(360, 800), (390, 844), (768, 900), (1280, 900)]:
            page.set_viewport_size({"width": width, "height": height})
            context.clear_cookies()
            routes = [("login", "/", ".auth-panel")]
            for label, route, selector in routes:
                page.goto(base + route, wait_until="networkidle")
                page.evaluate("document.fonts.ready")
                report.append(capture(page, artifacts, label, width, selector))
            sign_in(page, base)
            for label, route, selector in [("reviews", "/criticas", ".card-grid"), ("catalog", "/catalogo", ".catalog-grid"),
                ("connections", "/conexoes?aba=recebidas", ".connection-list"),
                ("settings", "/configuracoes?secao=aparencia", ".settings-panel"), ("chat", "/mensagens", ".chat-workspace")]:
                page.goto(base + route, wait_until="networkidle")
                page.evaluate("document.fonts.ready")
                report.append(capture(page, artifacts, label, width, selector))
            context.clear_cookies()
            sign_in(page, base, "fakeadmin")
            page.goto(base + "/admin", wait_until="networkidle")
            page.evaluate("document.fonts.ready")
            report.append(capture(page, artifacts, "admin", width, ".admin-stats"))
        (artifacts / "metrics.json").write_text(json.dumps({"screens": report, "consoleErrors": errors}, ensure_ascii=False, indent=2), encoding="utf-8")
        print("Responsive evidence:", artifacts)
        print(json.dumps([{k: v for k, v in item.items() if k != "axe"} for item in report], ensure_ascii=False))
        assert not errors, errors
        if phase != "before":
            assert all(item["scrollWidth"] <= item["width"] for item in report)
            assert all(item["firstViewport"] for item in report), report
            assert not [item for item in report if item["axe"]], report
    finally:
        context.close()


def capture(page, artifacts, label, width, selector):
    assert page.title() and page.locator("main").inner_text().strip()
    geometry = page.evaluate(GEOMETRY, selector)
    page.screenshot(path=str(artifacts / f"{label}-{width}.png"), full_page=True)
    page.screenshot(path=str(artifacts / f"{label}-{width}-viewport.png"), full_page=False)
    page.add_script_tag(path=str(ROOT / "node_modules" / "axe-core" / "axe.min.js"))
    violations = page.evaluate("""async () => (await axe.run(document, {runOnly: {type:'tag',
        values:['wcag2a','wcag2aa','wcag21aa','wcag22aa','best-practice']}})).violations.map(v =>
        ({id:v.id, impact:v.impact, targets:v.nodes.map(n => n.target)}))""")
    return {"screen": label, **geometry, "axe": violations}


@pytest.mark.parametrize("javascript", [True, False])
def test_native_mobile_navigation_filters_sections_and_writes(responsive_browser, javascript):
    from playwright.sync_api import expect
    browser, base = responsive_browser
    context = browser.new_context(java_script_enabled=javascript, bypass_csp=True,
        viewport={"width": 360, "height": 800}, reduced_motion="reduce")
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    artifacts = ROOT / ".runtime" / "responsive-qa" / "after"
    artifacts.mkdir(parents=True, exist_ok=True)
    suffix = "js" if javascript else "nojs"
    try:
        sign_in(page, base)
        page.goto(base + "/criticas")
        menu = page.locator("[data-nav-toggle]")
        assert not page.locator("#primary-nav").is_visible()
        menu.focus()
        page.keyboard.press("Enter")
        expect(page.locator("#primary-nav")).to_be_visible()
        assert menu.bounding_box()["height"] >= 44
        page.screenshot(path=str(artifacts / f"mobile-menu-{suffix}.png"))
        if javascript:
            page.keyboard.press("Escape")
            expect(menu).to_be_focused()
        else:
            page.keyboard.press("Enter")
        expect(page.locator("#primary-nav")).not_to_be_visible()
        filters = page.locator(".filter-disclosure")
        assert not filters.evaluate("node => node.open")
        filters.locator("summary").click()
        page.locator("#filter-minimum").fill("90")
        page.locator(".filter-apply").click()
        expect(page.locator(".empty-state")).to_contain_text("Nenhuma crítica encontrada")
        assert page.locator(".filter-disclosure").evaluate("node => node.open")
        assert page.locator("#filter-minimum").input_value() == "90"
        page.screenshot(path=str(artifacts / f"feed-filters-applied-{suffix}.png"), full_page=True)
        page.locator(".clear-filters").click()
        expect(page.locator(".filter-disclosure")).to_have_js_property('open',False)
        expect(page.locator('[data-review-card]')).to_have_count(6)
        heights = page.locator("[data-review-card]").evaluate_all("nodes => nodes.map(n => n.getBoundingClientRect().height)")
        assert len(heights) == 6 and max(heights) - min(heights) < 1
        page.goto(base + "/catalogo")
        page.locator(".backlog-filter-disclosure > summary").click()
        page.locator("#backlog-q").fill("História fictícia 4")
        page.locator(".backlog-filters button[type=submit]").click()
        assert page.locator("#backlog-q").input_value() == "História fictícia 4"
        assert page.locator(".backlog-filter-disclosure").evaluate("node => node.open")
        expect(page.locator(".catalog-work")).to_have_count(1)
        page.locator(".catalog-work [data-backlog-add] button").click()
        if not javascript:
            expect(page.locator("[data-backlog-item]")).to_contain_text("História fictícia 4")
            page.goto(base + "/catalogo")
        expect(page.locator(".catalog-added")).to_be_visible()
        page.goto(base + "/conexoes?aba=recebidas")
        assert not page.locator(".section-disclosure").evaluate("node => node.open")
        assert page.locator(".connection-list").bounding_box()["y"] < 500
        accept = page.locator('[data-connection-row="2"] [data-friend-action="accept"]')
        assert accept.bounding_box()["height"] >= 44
        accept.click()
        expect(page.locator('[data-connection-row="2"]')).to_have_count(0)
        if javascript:
            expect(page.locator("#connections-title")).to_be_focused()
        page.locator(".section-disclosure > summary").click()
        page.locator(".connections-nav").get_by_role("link", name="Amigos", exact=False).click()
        expect(page.locator('[data-connection-row="2"]')).to_contain_text("Conversar")
        page.goto(base + "/configuracoes")
        assert not page.locator(".section-disclosure").evaluate("node => node.open")
        page.locator(".section-disclosure > summary").click()
        page.locator(".settings-nav").get_by_role("link", name="Privacidade", exact=True).click()
        page.locator("#setting-message_policy").select_option("friends")
        page.locator("[data-settings-save]").click()
        expect(page.locator(".flashes")).to_contain_text("Preferências salvas")
        assert page.locator("#setting-message_policy").input_value() == "friends"
        page.goto(base + "/configuracoes")
        assert page.locator(".settings-switch").first.bounding_box()["height"] >= 44
        page.screenshot(path=str(artifacts / f"settings-native-{suffix}.png"))
        page.locator(".footer-column").last.locator("summary").click()
        expect(page.locator(".footer-links")).to_be_visible()
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        if javascript:
            audit = capture(page, artifacts, "settings-open-footer", 360, ".settings-panel")
            assert not audit["axe"], audit
        assert not errors, errors
    finally:
        context.close()


def test_desktop_navigation_remains_usable_without_javascript(responsive_browser):
    browser, base = responsive_browser
    context = browser.new_context(java_script_enabled=False, viewport={"width": 1280, "height": 900})
    page = context.new_page()
    try:
        page.goto(base + "/feed")
        assert page.locator("[data-nav-toggle]").is_visible()
        page.locator("[data-nav-toggle]").click()
        assert page.locator("#primary-nav").is_visible()
        page.locator("#primary-nav").get_by_role("link", name="Catálogo", exact=True).click()
        assert page.locator("h1").inner_text() == "Um mundo para descobrir."
        page.locator(".backlog-filter-disclosure > summary").click()
        assert page.locator("#backlog-q").is_visible()
        assert page.locator(".backlog-filter-disclosure > summary").is_visible()
        page.locator(".backlog-filter-disclosure > summary").click()
        assert not page.locator("#backlog-q").is_visible()
    finally:
        context.close()
