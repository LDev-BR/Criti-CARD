"""Settings save/preview, keyboard chat and no-JS mobile actions in a real browser."""
import os

import pytest

from test_chat import app
from test_browser_chat import chat_browser, login

pytestmark = pytest.mark.skipif(os.getenv('CRITICARD_BROWSER_TESTS') != '1', reason='Optional browser regressions')


def test_appearance_preview_discard_save_and_section_search(chat_browser):
    from playwright.sync_api import expect
    browser, origin = chat_browser
    context = browser.new_context(viewport={'width': 1280, 'height': 900}, reduced_motion='no-preference')
    page = context.new_page()
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    login(page, origin, 'alice')
    page.goto(origin + '/configuracoes')
    expect(page.get_by_role('heading', name='Configurações', exact=True)).to_be_visible()
    expect(page.locator('[data-settings-save]')).to_be_disabled()
    page.get_by_text('Meia-noite', exact=True).click()
    page.locator('#setting-high_contrast').check()
    expect(page.locator('html')).to_have_attribute('data-theme', 'midnight')
    expect(page.locator('html')).to_have_attribute('data-high-contrast', 'true')
    expect(page.locator('[data-settings-dirty]')).to_contain_text('alterações para salvar')
    page.get_by_role('button', name='Descartar', exact=True).click()
    expect(page.locator('html')).to_have_attribute('data-theme', 'graphite')
    expect(page.locator('html')).to_have_attribute('data-high-contrast', 'false')
    page.get_by_text('Meia-noite', exact=True).click()
    page.locator('#setting-reduce_motion').check()
    page.locator('#setting-card_hover').uncheck()
    page.get_by_role('button', name='Salvar alterações', exact=True).click()
    expect(page.get_by_text('Preferências salvas.', exact=True)).to_be_visible()
    page.reload()
    expect(page.locator('html')).to_have_attribute('data-theme', 'midnight')
    expect(page.locator('html')).to_have_attribute('data-card-hover', 'false')
    expect(page.locator('html')).to_have_attribute('data-reduce-motion', 'true')
    page.locator('#settings-search').fill('senha')
    expect(page.locator('[data-settings-area]:visible')).to_have_count(1)
    page.locator('#settings-search').press('Enter')
    expect(page).to_have_url(origin + '/configuracoes?secao=conta')
    expect(page.locator('#settings-title')).to_have_text('Conta e segurança')
    page.locator('#password-new').fill('AnotherPass2!')
    page.locator('[data-password-toggle="password-new"]').click()
    expect(page.locator('#password-new')).to_have_attribute('type', 'text')
    page.locator('[data-password-toggle="password-new"]').click()
    expect(page.locator('#password-new')).to_have_attribute('type', 'password')
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    assert not errors
    context.close()


def test_chat_keyboard_previews_and_timestamps_use_saved_preferences(chat_browser):
    from playwright.sync_api import expect
    browser, origin = chat_browser
    context = browser.new_context(reduced_motion='reduce')
    page = context.new_page()
    login(page, origin, 'alice')
    page.goto(origin + '/configuracoes?secao=chat')
    for name in ('chat_enter_send', 'chat_preview', 'chat_timestamps'):
        page.locator('#setting-' + name).uncheck()
    page.get_by_role('button', name='Salvar alterações', exact=True).click()
    expect(page.get_by_text('Preferências salvas.', exact=True)).to_be_visible()
    page.goto(origin + '/mensagens')
    page.locator('#chat-target').fill('BOB')
    page.get_by_role('button', name='Conversar', exact=True).click()
    expect(page.locator('[data-chat-status]')).to_have_text('Conectado')
    page.locator('#chat-body').fill('Primeira linha')
    page.locator('#chat-body').press('Enter')
    expect(page.locator('.chat-message')).to_have_count(0)
    assert '\n' in page.locator('#chat-body').input_value()
    page.locator('#chat-body').press('End')
    page.locator('#chat-body').type('Segunda linha')
    page.get_by_role('button', name='Enviar', exact=True).click()
    expect(page.locator('.chat-message')).to_have_count(1)
    expect(page.locator('.chat-bubble time')).to_be_hidden()
    expect(page.locator('[data-chat-preview]')).to_be_hidden()
    context.close()


def test_native_mobile_preferences_and_unblock_work_without_javascript(chat_browser, app):
    from playwright.sync_api import expect
    from criticard.social.service import set_block
    with app.app_context():
        set_block(1, 2, True)
    browser, origin = chat_browser
    context = browser.new_context(java_script_enabled=False, viewport={'width': 360, 'height': 800})
    page = context.new_page()
    login(page, origin, 'alice')
    page.goto(origin + '/configuracoes?secao=notificacoes')
    page.locator('#setting-notify_likes').uncheck()
    page.get_by_role('button', name='Salvar alterações', exact=True).click()
    expect(page.get_by_text('Preferências salvas.', exact=True)).to_be_visible()
    expect(page.locator('#setting-notify_likes')).not_to_be_checked()
    page.locator('.section-disclosure > summary').click()
    page.locator('.settings-nav').get_by_role('link', name='Pessoas bloqueadas', exact=True).click()
    expect(page.locator('.settings-block-row')).to_contain_text('Bob')
    page.get_by_role('button', name='Desbloquear', exact=True).click()
    expect(page.locator('.settings-block-row')).to_have_count(0)
    expect(page.get_by_text('Nenhuma pessoa bloqueada.', exact=True)).to_be_visible()
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    context.close()


def test_mobile_section_search_keeps_keyboard_focus_and_native_navigation(chat_browser):
    from playwright.sync_api import expect
    browser, origin = chat_browser
    context = browser.new_context(viewport={'width': 360, 'height': 800}, reduced_motion='reduce')
    page = context.new_page()
    try:
        login(page, origin, 'alice')
        page.goto(origin + '/configuracoes')
        page.locator('.section-disclosure > summary').click()
        search = page.locator('#settings-search')
        search.fill('senha')
        expect(search).to_be_focused()
        expect(page.locator('[data-settings-area]:visible')).to_have_count(1)
        page.keyboard.press('Tab')
        expect(page.locator('[data-settings-area]:visible')).to_be_focused()
        search.fill('nenhuma-opcao')
        search.press('Enter')
        expect(search).to_be_focused()
        expect(page.locator('[data-settings-search-status]')).to_contain_text('Nenhuma área encontrada')
        search.fill('')
        expect(page.locator('[data-settings-area]:visible')).to_have_count(8)
        search.fill('senha')
        search.press('Enter')
        expect(page).to_have_url(origin + '/configuracoes?secao=conta')
        expect(page.locator('#settings-title')).to_have_text('Conta e segurança')
        assert not page.locator('.section-disclosure').evaluate('node => node.open')
    finally:
        context.close()


def test_card_preferences_hide_excerpt_and_keep_click_reading_and_fixed_size(chat_browser, app):
    from playwright.sync_api import expect
    from sqlalchemy import insert
    from criticard.db import get_db
    from criticard.models import Card
    with app.app_context():
        db = get_db()
        with db:
            db.execute(insert(Card).values(titulo='Elden Ring', capa='invalid-cover',
                sobre='Minha crítica permanece inteira.', nota=90, author_id=1, obra_id=1))
    browser, origin = chat_browser
    context = browser.new_context(reduced_motion='reduce')
    page = context.new_page()
    login(page, origin, 'alice')
    page.goto(origin + '/configuracoes')
    page.locator('#setting-card_excerpt').uncheck()
    page.locator('#setting-card_hover').uncheck()
    page.locator('#setting-text_size').select_option('large')
    page.locator('#setting-card_density').select_option('compact')
    page.get_by_role('button', name='Salvar alterações', exact=True).click()
    expect(page.get_by_text('Preferências salvas.', exact=True)).to_be_visible()
    page.clock.install()
    page.goto(origin + '/criticas')
    card = page.locator('[data-review-card]')
    expect(card.locator('.card-excerpt')).to_be_hidden()
    assert card.bounding_box()['height'] == 510
    assert page.locator('.card-grid').evaluate('node => getComputedStyle(node).gap') == '14px'
    card.locator('.card-surface').hover()
    page.clock.run_for(400)
    expect(card.locator('[data-card-back]')).to_be_hidden()
    card.get_by_role('link', name='Ler crítica', exact=True).click()
    expect(card.locator('[data-card-back]')).to_be_visible()
    expect(card.locator('[data-reader-page]')).to_contain_text('Minha crítica permanece inteira.')
    assert card.locator('[data-reader-page]').evaluate('node => getComputedStyle(node).fontSize') == '16px'
    context.close()
