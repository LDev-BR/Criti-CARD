import io
import os
from pathlib import Path

import pytest
from PIL import Image

from conftest import rows
from test_browser_reading import reading_page as crop_page
from test_browser_forms import origin, sign_in

pytestmark = pytest.mark.skipif(os.getenv("CRITICARD_BROWSER_TESTS") != "1", reason="Optional browser tests")


def portrait_file():
    stream = io.BytesIO()
    Image.new("RGB", (600, 900), "#baa375").save(stream, format="PNG")
    return {"name":"portrait.png", "mimeType":"image/png", "buffer":stream.getvalue()}


def test_admin_cover_crop_persists_as_curated_card_and_mobile_preview(crop_page, app):
    page = crop_page
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on("console", lambda message: errors.append(f"{message.text} [{message.location.get('url', '')}]") if message.type == "error" else None)
    page.goto(origin(page) + '/')
    page.locator('#username').fill('admin@example.com')
    page.locator('#senha').fill('Password1!')
    page.locator('.form-submit').click()
    page.wait_for_url('**/dashboard')
    page.set_viewport_size({"width":390,"height":844})
    page.goto(origin(page) + "/admin/obras/nova")
    page.locator('#titulo').fill('A história do recorte')
    page.locator("#categoria_id").select_option(label="Mangás")
    page.locator("#capa").set_input_files(portrait_file())
    original = page.locator("#cover-preview").get_attribute("src")
    page.locator("[data-crop-image]").click()
    page.locator("#crop-dialog").wait_for(state="visible")
    assert page.locator("#crop-dialog").is_visible()
    page.keyboard.press("Escape")
    assert page.locator("#cover-preview").get_attribute("src") == original
    assert page.locator("#capa").evaluate("input => input.files[0].name") == "portrait.png"
    page.locator("[data-crop-image]").click()
    page.locator("#crop-dialog").wait_for(state="visible")
    page.locator("#crop-zoom").focus()
    page.keyboard.press("End")
    assert page.locator("[data-crop-zoom-label]").inner_text() == "300%"
    bounds = page.locator('[data-crop-canvas]').bounding_box()
    center_x, center_y = bounds['x'] + bounds['width']/2, bounds['y'] + bounds['height']/2
    page.mouse.move(center_x, center_y)
    page.mouse.down()
    page.mouse.move(center_x + 24, center_y + 12, steps=4)
    page.mouse.up()
    assert int(page.locator('#crop-x').input_value()) < 50
    page.locator("#crop-y").focus()
    page.keyboard.press("Home")
    page.locator("[data-crop-apply]").click()
    page.locator('[data-upload-status]').filter(has_text="Recorte aplicado").wait_for(state="visible")
    assert not page.locator("#crop-dialog").is_visible()
    assert page.locator("#cover-preview").evaluate("async image => {await image.decode();return [image.naturalWidth,image.naturalHeight]}") == [1050,700]
    page.locator('.form-submit').click()
    page.wait_for_url('**/admin/obras*')
    work = rows(app, "SELECT * FROM obras WHERE titulo='A história do recorte'")[0]
    with Image.open(Path(app.config['CAPA_FOLDER']) / work['capa']) as image:
        assert image.size == (1050, 700)
    page.goto(origin(page) + "/cadastro_cards")
    page.locator("#categoria_id").select_option(label="Mangás")
    page.locator("#obra_id").select_option(str(work['id']))
    assert page.locator("input[type=file]").count() == 0
    assert page.locator("[data-draft-title]").inner_text() == "A história do recorte"
    assert page.locator("[data-draft-category]").inner_text() == "Mangás"
    assert page.locator('#cover-preview').get_attribute('src').endswith('/cards/' + work['capa'])
    page.locator("#sobre").fill("Uma história inesquecível.")
    page.locator("#nota").fill("98")
    page.locator("[data-open-draft]").click()
    assert page.locator(".draft-preview-dialog").is_visible()
    assert page.locator(".draft-preview-dialog [data-draft-score]").inner_text() == "98"
    page.keyboard.press("Escape")
    page.locator('[data-open-draft][aria-expanded="false"]').wait_for(state="visible")
    assert page.locator("[data-open-draft]").get_attribute("aria-expanded") == "false"
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    page.locator(".form-submit").click()
    page.wait_for_url("**/dashboard")
    card = rows(app, "SELECT * FROM cards WHERE id=2")[0]
    with Image.open(Path(app.config["CAPA_FOLDER"]) / card["capa"]) as image:
        assert image.size == (1050,700)
    assert card['capa'] == work['capa']
    assert card["titulo"] == "A história do recorte" and card["obra_id"] == work['id']
    assert not errors


def test_avatar_crop_is_square_and_can_be_replaced(crop_page):
    page = crop_page
    page.goto(origin(page) + "/cadastro")
    page.locator(".optional-profile > summary").click()
    page.locator("#imagem").set_input_files(portrait_file())
    page.locator("[data-crop-image]").click()
    page.locator("[data-crop-apply]").click()
    page.locator('[data-upload-status]').filter(has_text="Recorte aplicado").wait_for(state="visible")
    assert page.locator("#avatar-preview").evaluate("async image => {await image.decode();return [image.naturalWidth,image.naturalHeight]}") == [768,768]
    page.locator("[data-upload-reset]").click()
    assert page.locator("#imagem").input_value() == ""
    assert page.locator("#avatar-preview").get_attribute("src").endswith("default-avatar.svg")


def test_legacy_card_title_edit_and_conversion_to_catalog(crop_page, app):
    page = crop_page
    sign_in(page)
    page.goto(origin(page) + '/editar_card/1')
    page.locator('#titulo').fill('Título antigo corrigido')
    page.locator('#sobre').fill('Crítica antiga revisada.')
    assert page.locator('[data-draft-title]').inner_text() == 'Título antigo corrigido'
    page.locator('.form-submit').click()
    page.wait_for_url('**/dashboard')
    assert rows(app, 'SELECT titulo,obra_id FROM cards WHERE id=1')[0][:] == ('Título antigo corrigido', None)
    page.goto(origin(page) + '/editar_card/1')
    page.locator('#categoria_id').select_option(label='Mangás')
    page.locator('#obra_id').select_option(label='Berserk')
    assert page.locator('#titulo').get_attribute('readonly') is not None
    page.locator('#categoria_id').select_option(label='Jogos')
    assert page.locator('#titulo').input_value() == 'Título antigo corrigido'
    assert page.locator('#titulo').get_attribute('readonly') is None
    page.locator('#obra_id').select_option(label='Elden Ring')
    page.locator('.form-submit').click()
    page.wait_for_url('**/dashboard')
    card = rows(app, 'SELECT titulo,obra_id FROM cards WHERE id=1')[0]
    assert card['titulo'] == 'Elden Ring' and card['obra_id'] is not None
