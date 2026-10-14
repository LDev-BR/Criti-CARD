"""Catalogue art follows the actual publishing and reading journeys."""
import os
import json
from pathlib import Path
import tempfile
from urllib.parse import urlsplit

import pytest

from conftest import rows
from criticard.config import ROOT
from test_browser_forms import origin, sign_in
from test_browser_reading import reading_page

pytestmark = pytest.mark.skipif(os.getenv('CRITICARD_BROWSER_TESTS') != '1',
    reason='Set CRITICARD_BROWSER_TESTS=1 to run Edge/Playwright checks')


def test_search_curated_preview_publish_and_expanded_art(reading_page, app):
    from playwright.sync_api import expect
    page = reading_page
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    sign_in(page)
    page.goto(origin(page) + '/cadastro_cards')
    page.locator('[data-work-search]').fill('eld')
    assert page.locator('#obra_id option').count() == 2
    page.locator('#obra_id').select_option(label='Elden Ring')
    preview = page.locator('[data-draft-cover]')
    assert 'catalog-art--col-0' in preview.get_attribute('class')
    source = page.locator('#cover-preview').get_attribute('src')
    assert source.endswith('/catalog/jogos-atlas.png')
    expect(page.locator('#cover-preview')).to_have_js_property('complete', True)
    assert page.locator('#cover-preview').evaluate('img => img.naturalWidth > 0')
    assert page.locator('input[type=file]').count() == 0
    page.locator('[data-clear-work-search]').click()
    page.locator('#obra_id').select_option(label='Hollow Knight')
    assert 'catalog-art--col-1' in preview.get_attribute('class')
    page.locator('#obra_id').select_option(label='Elden Ring')
    assert page.locator('#cover-preview').get_attribute('src') == source
    assert preview.locator('.catalog-art-frame').count() == 1
    page.locator('#nota').fill('92')
    page.locator('#sobre').fill('Uma jornada para guardar na coleção.')
    page.locator('.form-submit').click()
    page.wait_for_url('**/dashboard')
    assert rows(app, 'SELECT capa FROM cards WHERE id=2')[0][0] == 'catalog:jogos:0'
    card = page.locator('#card-2')
    card.locator('.read-review').click()
    card.locator('[data-expand-review]').click()
    dialog = page.locator('#review-dialog')
    assert urlsplit(dialog.locator('[data-dialog-cover]').get_attribute('src')).path == source
    assert dialog.locator('.catalog-art-frame').count() == 1
    assert 'catalog-art--col-0' in dialog.locator('[data-dialog-art]').get_attribute('class')
    assert not errors


def test_catalog_publication_without_upload_or_javascript(reading_page, app):
    page = reading_page.context.browser.new_page(java_script_enabled=False, viewport={'width': 360, 'height': 800})
    try:
        page.goto(origin(reading_page) + '/')
        sign_in(page)
        page.goto(origin(page) + '/cadastro_cards')
        assert not page.locator('[data-work-search]').is_visible()
        page.locator('#obra_id').select_option(label='Duna')
        page.locator('#nota').fill('90')
        page.locator('#sobre').fill('Uma leitura memorável.')
        page.locator('.form-submit').click()
        page.wait_for_url('**/dashboard')
        assert rows(app, 'SELECT capa FROM cards WHERE id=2')[0][0] == 'catalog:livros:1'
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    finally:
        page.close()


def test_composer_desktop_mobile_keyboard_and_legacy_preview_accessibility(reading_page):
    """Audit rendered states while the draft and mobile dialog actually change."""
    from playwright.sync_api import expect
    base = origin(reading_page)
    artifacts = Path(os.getenv('CRITICARD_ADMIN_QA_ARTIFACTS') or
        tempfile.mkdtemp(prefix='criticard-composer-qa-'))
    artifacts.mkdir(parents=True, exist_ok=True)
    context = reading_page.context.browser.new_context(bypass_csp=True,
        viewport={'width': 1280, 'height': 900}, reduced_motion='reduce')
    page = context.new_page()
    errors, report = [], []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.on('console', lambda message: errors.append(message.text)
        if message.type in ('error', 'warning') else None)

    def audit(label):
        page.evaluate('document.fonts.ready')
        assert page.title().endswith('Criti-CARD')
        assert page.locator('main').inner_text().strip()
        assert page.locator('h1').count() == 1
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.evaluate('window.scrollTo(0, 0)')
        page.screenshot(path=str(artifacts / (label + '.png')), full_page=not label.endswith('preview'))
        page.add_script_tag(path=str(ROOT / 'node_modules' / 'axe-core' / 'axe.min.js'))
        violations = page.evaluate("""async () => (await axe.run(document, {runOnly:
            {type:'tag', values:['wcag2a','wcag2aa','wcag21aa','wcag22aa','best-practice']}}))
            .violations.map(v => ({id:v.id, impact:v.impact, targets:v.nodes.map(n => n.target)}))""")
        report.append({'screen': label, 'url': page.url, 'violations': violations})

    try:
        page.goto(base + '/')
        sign_in(page)
        page.goto(base + '/cadastro_cards')
        audit('composer-empty')
        page.locator('[data-work-search]').fill('hollow')
        page.locator('#obra_id').select_option(label='Hollow Knight')
        page.locator('#sobre').fill('Atmosfera marcante e uma jornada de descobertas.')
        page.locator('#nota-slider').focus()
        page.keyboard.press('End')
        expect(page.locator('[data-draft-score]')).to_have_text('100')
        audit('composer-filled')
        page.set_viewport_size({'width': 360, 'height': 800})
        audit('composer-mobile')
        page.locator('[data-open-draft]').click()
        expect(page.locator('.draft-preview-dialog')).to_be_visible()
        expect(page.locator('.draft-preview-dialog [data-draft-title]')).to_have_text('Hollow Knight')
        audit('composer-mobile-preview')
        page.keyboard.press('Escape')
        expect(page.locator('[data-open-draft]')).to_be_focused()
        assert page.locator('[data-open-draft]').get_attribute('aria-expanded') == 'false'
        page.set_viewport_size({'width': 1280, 'height': 900})
        page.goto(base + '/editar_card/1')
        page.locator('#titulo').fill('Uma crítica antiga revisada')
        expect(page.locator('[data-draft-title]')).to_have_text('Uma crítica antiga revisada')
        audit('composer-legacy')
        (artifacts / 'composer-axe.json').write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        assert not errors, errors
        assert not [entry for entry in report if entry['violations']], json.dumps(report, ensure_ascii=False)
    finally:
        context.close()
