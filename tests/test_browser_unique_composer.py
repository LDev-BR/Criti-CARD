"""One review per catalog work, with an accessible composer and fake data."""
import os

import pytest

from conftest import rows
from criticard.db import get_db
from test_browser_forms import origin, sign_in
from test_browser_reading import reading_page

pytestmark = pytest.mark.skipif(os.getenv('CRITICARD_BROWSER_TESTS') != '1',
    reason='Set CRITICARD_BROWSER_TESTS=1 to run Edge/Playwright checks')


def reviewed_work(app):
    with app.app_context():
        db = get_db()
        work_id = db.execute("SELECT id FROM obras WHERE titulo='Duna'").fetchone()[0]
        db.execute('INSERT INTO cards (titulo,capa,sobre,nota,author_id,obra_id) VALUES (?,?,?,?,?,?)',
            ('Duna', 'catalog:livros:1', 'Minha primeira avaliação.', 90, 1, work_id))
        db.commit()
        card_id = db.execute('SELECT id FROM cards WHERE author_id=1 AND obra_id=?', (work_id,)).fetchone()[0]
        return work_id, card_id


def test_reviewed_selection_blocks_publication_and_preserves_current_text(reading_page, app):
    """A reviewed option must prevent a second publication and offer its editor."""
    from playwright.sync_api import expect
    page = reading_page
    work_id, card_id = reviewed_work(app)
    sign_in(page)
    page.goto(origin(page) + '/cadastro_cards')
    page.locator('#sobre').fill('Este texto ainda está sendo preparado.')
    page.locator('#nota').fill('85')
    page.locator('#obra_id').select_option(str(work_id))
    notice = page.locator('[data-existing-review]')
    expect(notice).to_be_visible()
    expect(notice).to_contain_text('Você já avaliou Duna')
    expect(page.locator('[data-existing-edit]')).to_have_attribute('href', f'/editar_card/{card_id}')
    expect(page.locator('.form-submit')).to_be_disabled()
    expect(page.locator('[data-draft-title]')).to_have_text('Duna')
    assert page.locator('#sobre').input_value() == 'Este texto ainda está sendo preparado.'
    assert page.evaluate('localStorage.length') == 0
    page.locator('[data-work-search]').fill('dun')
    expect(notice).to_be_visible()
    page.locator('[data-clear-work-search]').click()
    page.locator('#obra_id').select_option(label='1984')
    expect(notice).to_be_hidden()
    expect(page.locator('.form-submit')).to_be_enabled()
    assert page.locator('#sobre').input_value() == 'Este texto ainda está sendo preparado.'
    assert rows(app, 'SELECT COUNT(*) FROM cards WHERE author_id=1 AND obra_id=?', (work_id,))[0][0] == 1


def test_mobile_preview_action_stays_in_flow_and_restores_keyboard_focus(reading_page):
    """Preview must never cover form controls as the user scrolls or types."""
    from playwright.sync_api import expect
    page = reading_page
    sign_in(page)
    page.set_viewport_size({'width': 360, 'height': 800})
    page.goto(origin(page) + '/cadastro_cards')
    trigger = page.locator('[data-open-draft]')
    assert trigger.evaluate("node => getComputedStyle(node).position") not in ('fixed', 'sticky')
    assert trigger.evaluate("node => node.closest('.composer-actions') !== null")
    page.locator('#obra_id').select_option(label='Hollow Knight')
    page.locator('#sobre').fill('Uma crítica preparada no celular.')
    trigger.click()
    expect(page.locator('.draft-preview-dialog')).to_be_visible()
    expect(page.locator('.draft-preview-dialog [data-draft-title]')).to_have_text('Hollow Knight')
    page.keyboard.press('Escape')
    expect(trigger).to_be_focused()
    page.set_viewport_size({'width': 360, 'height': 400})
    page.locator('#sobre').focus()
    page.locator('#sobre').scroll_into_view_if_needed()
    assert page.locator('#sobre').evaluate('node => node === document.activeElement')
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    assert page.locator('#sobre').input_value() == 'Uma crítica preparada no celular.'


def test_delayed_preview_close_does_not_take_focus_from_a_new_form_action(reading_page):
    from playwright.sync_api import expect
    page = reading_page
    sign_in(page)
    page.set_viewport_size({'width':360, 'height':800})
    page.goto(origin(page) + '/cadastro_cards')
    page.locator('#sobre').fill('Texto preservado')
    page.locator('[data-open-draft]').click()
    expect(page.locator('.draft-preview-dialog')).to_be_visible()
    # The native dialog restores focus immediately; its close event can be
    # delivered after the user has already returned to writing their critique.
    assert page.evaluate("""() => {
        const dialog = document.querySelector('.draft-preview-dialog');
        dialog.close();
        const critique = document.querySelector('#sobre');
        critique.focus();
        dialog.dispatchEvent(new Event('close'));
        return document.activeElement === critique;
    }""")
    expect(page.locator('#sobre')).to_be_focused()
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    assert page.locator('#sobre').input_value() == 'Texto preservado'


def test_duplicate_server_response_keeps_text_and_edit_link_without_javascript(reading_page, app):
    """Server-only users can recover from a duplicate without losing their review."""
    from playwright.sync_api import expect
    work_id, card_id = reviewed_work(app)
    page = reading_page.context.browser.new_page(java_script_enabled=False,
        viewport={'width': 390, 'height': 800})
    try:
        page.goto(origin(reading_page) + '/')
        sign_in(page)
        page.goto(origin(page) + '/cadastro_cards')
        page.locator('#obra_id').select_option(str(work_id))
        page.locator('#nota').fill('84')
        page.locator('#sobre').fill('Quero atualizar a minha opinião sobre esta obra.')
        page.locator('.form-submit').click()
        page.wait_for_load_state('networkidle')
        expect(page.locator('[data-existing-review]')).to_be_visible()
        expect(page.locator('[data-existing-edit]')).to_have_attribute('href', f'/editar_card/{card_id}')
        assert page.locator('#sobre').input_value() == 'Quero atualizar a minha opinião sobre esta obra.'
        assert rows(app, 'SELECT COUNT(*) FROM cards WHERE author_id=1 AND obra_id=?', (work_id,))[0][0] == 1
        page.locator('[data-existing-edit]').click()
        page.wait_for_url(f'**/editar_card/{card_id}')
        assert page.locator('#sobre').input_value() == 'Minha primeira avaliação.'
    finally:
        page.close()
