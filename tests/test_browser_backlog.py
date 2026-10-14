"""Catalog -> collection -> explicit sharing, with and without JavaScript."""
import os
from pathlib import Path

import pytest

from conftest import rows
from test_browser_forms import origin, sign_in
from test_browser_reading import reading_page as backlog_page

pytestmark = pytest.mark.skipif(os.getenv("CRITICARD_BROWSER_TESTS") != "1", reason="Optional browser regressions")


def screenshot(page, name):
    destination = os.getenv("CRITICARD_BACKLOG_SCREENSHOTS")
    if destination:
        page.screenshot(path=str(Path(destination) / (name + ".png")), full_page=False)


def test_catalog_add_progress_sharing_and_mobile_layout(backlog_page, app):
    page = backlog_page
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
    sign_in(page)
    page.goto(origin(page) + "/catalogo")
    assert "Catálogo" in page.title()
    assert page.locator("[data-catalog-work]").count() == 30
    screenshot(page, "catalog-desktop")
    page.locator("#backlog-category").select_option("mangas")
    page.locator("#backlog-q").fill("Berserk")
    page.locator(".backlog-filters").get_by_role("button", name="Buscar", exact=True).click()
    page.wait_for_load_state("networkidle")
    assert page.locator("[data-catalog-work]").count() == 1
    with page.expect_response(lambda response: response.url.endswith("/backlog/add") and response.request.method == "POST") as added:
        page.locator("[data-backlog-add] button").click()
    assert added.value.status == 201, added.value.text()
    page.locator("[data-backlog-message]").get_by_text("Obra adicionada à sua coleção.").wait_for()
    assert page.locator("[data-backlog-add] button").is_disabled()
    assert rows(app, "SELECT status,visibility FROM backlog_items")[0]["visibility"] == "private"
    page.goto(origin(page) + "/backlog")
    assert page.locator("[data-backlog-item]").count() == 1
    assert page.locator(".backlog-status").inner_text() == "Quero ler"
    page.locator(".backlog-edit summary").click()
    page.locator('[name="status"]').select_option("in_progress")
    page.locator('[name="progress"]').fill("12")
    page.locator('[name="progress_unit"]').select_option("chapters")
    page.locator('[name="visibility"]').select_option("public")
    page.locator("[data-backlog-update] button").click()
    page.wait_for_load_state("networkidle")
    assert page.locator(".backlog-status").inner_text() == "Lendo"
    assert "12 capítulos" in page.locator(".backlog-item-meta").inner_text()
    screenshot(page, "backlog-desktop")
    visitor = page.context.browser.new_page(viewport={"width": 390, "height": 844})
    try:
        visitor.goto(origin(page) + "/colecao/alice")
        assert visitor.locator("[data-backlog-item]").count() == 1
        assert visitor.locator("[data-backlog-update]").count() == 0
        assert visitor.evaluate("document.documentElement.scrollWidth <= innerWidth")
    finally:
        visitor.close()
    page.set_viewport_size({"width": 390, "height": 844})
    for route in ("/catalogo", "/backlog"):
        page.goto(origin(page) + route)
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.wait_for_function("""() => [...document.images].filter(image => {
            const rect = image.getBoundingClientRect();
            return rect.top < innerHeight && rect.bottom > 0 && rect.width > 0;
        }).every(image => image.complete && image.naturalWidth > 0)""")
        screenshot(page, "catalog-mobile" if route == "/catalogo" else "backlog-mobile")
    assert not errors


def test_backlog_forms_without_javascript(backlog_page, app):
    page = backlog_page.context.browser.new_page(java_script_enabled=False, viewport={"width": 375, "height": 812})
    try:
        page.goto(origin(backlog_page) + "/")
        sign_in(page)
        page.goto(origin(page) + "/catalogo?categoria=jogos&q=Hades")
        page.locator("[data-backlog-add] button").click()
        page.wait_for_url(origin(page) + "/backlog")
        assert page.locator(".backlog-status").inner_text() == "Quero jogar"
        page.locator(".backlog-edit summary").click()
        page.locator('[name="status"]').select_option("completed")
        page.locator("[data-backlog-update] button").click()
        page.wait_for_load_state("networkidle")
        assert page.locator(".backlog-status").inner_text() == "Jogado"
        page.locator(".backlog-review-link").click()
        assert page.locator("#obra_id").input_value() == str(rows(app, "SELECT id FROM obras WHERE titulo='Hades'")[0][0])
        assert page.locator("#titulo").input_value() == "Hades"
        page.goto(origin(page) + "/backlog")
        page.locator(".backlog-edit summary").click()
        page.locator(".backlog-remove button").click()
        page.wait_for_load_state("networkidle")
        assert page.locator("[data-backlog-item]").count() == 0
        assert rows(app, "SELECT COUNT(*) FROM backlog_items")[0][0] == 0
    finally:
        page.close()
