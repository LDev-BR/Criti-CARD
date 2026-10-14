"""Optional browser regressions: CRITICARD_BROWSER_TESTS=1 enables these tests."""
import os
import shutil
from threading import Thread

import pytest
from PIL import Image
from werkzeug.serving import make_server

from criticard.config import ROOT
from criticard.db import get_db

pytestmark = pytest.mark.skipif(
    os.getenv("CRITICARD_BROWSER_TESTS") != "1",
    reason="Optional: install requirements-browser.txt and set CRITICARD_BROWSER_TESTS=1",
)


@pytest.fixture
def reading_page(app, tmp_path):
    from playwright.sync_api import sync_playwright
    assets = tmp_path / "browser-static"
    shutil.copytree(ROOT / "static", assets, ignore=shutil.ignore_patterns("uploads", "cards"))
    (assets / "cards").mkdir()
    (assets / "uploads").mkdir()
    Image.new("RGB", (32, 24), "#222222").save(assets / "cards" / "legacy.png")
    app.static_folder = str(assets)
    app.config.update(CAPA_FOLDER=str(assets / "cards"), UPLOAD_FOLDER=str(assets / "uploads"))
    with app.app_context():
        db = get_db()
        with db:
            db.execute("UPDATE cards SET titulo=?,sobre=? WHERE id=1",
                       ("Uma crítica com um título longo em duas linhas", "Muito boaMuito boa" * 170))
    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as playwright:
            channel = os.getenv("PLAYWRIGHT_CHANNEL") or ("msedge" if os.name == "nt" else None)
            browser = playwright.chromium.launch(channel=channel, headless=True)
            page = browser.new_page(viewport={"width": 1505, "height": 1045})
            page.goto(f"http://127.0.0.1:{server.server_port}/criticas", wait_until="networkidle")
            page.evaluate("document.fonts.ready")
            yield page
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_hover_does_not_remove_new_keyboard_focus(reading_page):
    card = reading_page.locator("#card-1")
    card.locator(".card-cover").hover()
    card.locator(".card-author").focus()
    # The defect is a delayed hover, so wait past that actual behavior's timer.
    reading_page.wait_for_timeout(400)
    assert card.locator(".card-author").evaluate("node => node === document.activeElement")
    assert card.locator("[data-card-front]").is_visible()


@pytest.mark.parametrize("height", [390, 300])
def test_landscape_reader_keeps_complete_lines_and_text(reading_page, height):
    card = reading_page.locator("#card-1")
    original = card.locator("[data-review-text]").evaluate("node => node.content.textContent")
    card.locator(".read-review").click()
    card.locator("[data-expand-review]").click()
    reading_page.set_viewport_size({"width": 844, "height": height})
    reading_page.wait_for_timeout(200)
    dialog = reading_page.locator("#review-dialog")
    viewport = dialog.locator("[data-reader-page]")
    assert viewport.evaluate("node => node.clientHeight >= parseFloat(getComputedStyle(node).lineHeight)")
    while not dialog.locator("[data-page-prev]").is_disabled():
        dialog.locator("[data-page-prev]").click()
    pages = []
    for _ in range(100):
        assert viewport.evaluate("node => node.scrollHeight <= node.clientHeight + 1")
        pages.append(viewport.text_content())
        if dialog.locator("[data-page-next]").is_disabled():
            break
        dialog.locator("[data-page-next]").click()
    else:
        pytest.fail("Reader created unusable one-character pages")
    assert "".join(pages) == original


def test_reader_uses_scroll_if_less_than_one_line_fits(reading_page):
    card = reading_page.locator("#card-1")
    original = card.locator("[data-review-text]").evaluate("node => node.content.textContent")
    card.locator(".read-review").click()
    card.locator("[data-expand-review]").click()
    viewport = reading_page.locator("#review-dialog [data-reader-page]")
    viewport.evaluate("node => Object.assign(node.style, {flex:'none', height:'10px'})")
    reading_page.locator('#review-dialog [data-reader-page].reader-scroll').wait_for(state="visible")
    assert viewport.text_content() == original
    assert reading_page.locator("#review-dialog [data-page-count]").inner_text() == "Texto completo"
    assert reading_page.locator("#review-dialog [data-page-next]").is_disabled()
