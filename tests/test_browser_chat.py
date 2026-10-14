"""Optional, auto-discovered browser proof with isolated users and assets."""
import os
import shutil
from threading import Thread

import pytest
from werkzeug.serving import make_server

from criticard.config import ROOT
from test_chat import app

pytestmark = pytest.mark.skipif(os.getenv('CRITICARD_BROWSER_TESTS') != '1', reason='Optional browser regressions')


@pytest.fixture
def chat_browser(app, tmp_path):
    from playwright.sync_api import sync_playwright
    assets = tmp_path / 'browser-static'
    shutil.copytree(ROOT / 'static', assets, ignore=shutil.ignore_patterns('uploads', 'cards'))
    app.static_folder = str(assets)
    server = make_server('127.0.0.1', 0, app, threaded=True)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel=os.getenv('PLAYWRIGHT_CHANNEL') or ('msedge' if os.name == 'nt' else None), headless=True)
            yield browser, f'http://127.0.0.1:{server.server_port}'
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def login(page, origin, name):
    page.goto(origin + '/')
    page.locator('#username').fill(name)
    page.locator('#senha').fill('Password1!')
    page.locator('button[type=submit]').first.click()
    page.wait_for_url(origin + '/dashboard')


def test_chat_live_delivery_reconnect_focus_and_mobile(chat_browser):
    from playwright.sync_api import expect
    browser, origin = chat_browser
    alice_context = browser.new_context(viewport={'width': 1280, 'height': 900})
    bob_context = browser.new_context(viewport={'width': 390, 'height': 844}, reduced_motion='reduce')
    alice, bob = alice_context.new_page(), bob_context.new_page()
    errors = []
    for page in [alice, bob]:
        page.on('pageerror', lambda error: errors.append(str(error)))
    login(alice, origin, 'alice')
    assert alice.goto(origin + '/mensagens').status == 200
    alice.locator('#chat-target').fill('BOB')
    alice.get_by_role('button', name='Conversar').click()
    conversation_url = alice.url
    login(bob, origin, 'bob')
    bob.goto(conversation_url)
    expect(alice.locator('[data-chat-status]')).to_have_text('Conectado')
    expect(bob.locator('[data-chat-status]')).to_have_text('Conectado')
    alice.locator('#chat-body').fill('Mensagem privada em tempo real')
    alice.get_by_role('button', name='Enviar', exact=True).click()
    expect(bob.locator('.chat-bubble p')).to_have_text('Mensagem privada em tempo real')
    expect(alice.locator('#chat-body')).to_be_focused()
    assert bob.evaluate('document.documentElement.scrollWidth <= innerWidth')
    bob_context.set_offline(True)
    expect(bob.locator('[data-chat-status]')).not_to_have_text('Conectado')
    alice.locator('#chat-body').fill('Chegou durante a reconexão')
    alice.get_by_role('button', name='Enviar', exact=True).click()
    expect(alice.locator('.chat-message')).to_have_count(2)
    bob_context.set_offline(False)
    expect(bob.locator('.chat-message')).to_have_count(2, timeout=15000)
    expect(bob.locator('.chat-bubble p').last).to_have_text('Chegou durante a reconexão')
    assert not errors
    alice_context.close()
    bob_context.close()


def test_chat_forms_work_without_javascript(chat_browser):
    from playwright.sync_api import expect
    browser, origin = chat_browser
    context = browser.new_context(java_script_enabled=False, viewport={'width': 375, 'height': 812})
    page = context.new_page()
    login(page, origin, 'alice')
    page.goto(origin + '/mensagens')
    page.locator('#chat-target').fill('BOB')
    page.get_by_role('button', name='Conversar').click()
    expect(page.locator('#chat-compose-help')).not_to_contain_text('Enter')
    page.locator('#chat-body').fill('Também funciona sem JavaScript')
    page.get_by_role('button', name='Enviar', exact=True).click()
    expect(page.locator('.chat-bubble p')).to_have_text('Também funciona sem JavaScript')
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    # A collapsed native menu can suspend its animation indefinitely. Capture
    # the actual scriptless chat state without awaiting hidden animations.
    page.screenshot(path=str(ROOT / '.runtime' / 'chat-no-js.png'), full_page=True, animations='disabled')
    context.close()


def test_edit_after_lost_acknowledgement_uses_a_new_message_id(chat_browser):
    from playwright.sync_api import expect
    browser, origin = chat_browser
    context = browser.new_context()
    page = context.new_page()
    # Deliberately remove realtime transport to exercise the HTTP recovery path.
    page.route('**/static/vendor/socket.io.min.js', lambda route: route.abort())
    login(page, origin, 'alice')
    page.goto(origin + '/mensagens')
    page.locator('#chat-target').fill('BOB')
    page.get_by_role('button', name='Conversar').click()
    expect(page.locator('[data-chat-status]')).to_have_text('Histórico atualizado')
    attempts = []
    def lose_first_reply(route):
        attempts.append(route.request.post_data_json)
        if len(attempts) == 1:
            assert route.fetch().status == 201
            route.abort()
        else:
            route.continue_()
    page.route('**/mensagens/*/enviar', lose_first_reply)
    page.locator('#chat-body').fill('Primeira mensagem salva, resposta perdida')
    page.get_by_role('button', name='Enviar', exact=True).click()
    expect(page.locator('[data-chat-error]')).to_be_visible()
    page.locator('#chat-body').fill('Agora quero enviar outra mensagem')
    page.get_by_role('button', name='Enviar', exact=True).click()
    expect(page.locator('.chat-bubble p').last).to_have_text('Agora quero enviar outra mensagem')
    history = page.request.get(page.url + '/historico').json()['messages']
    assert [message['body'] for message in history] == [
        'Primeira mensagem salva, resposta perdida', 'Agora quero enviar outra mensagem']
    assert attempts[0]['client_nonce'] != attempts[1]['client_nonce']
    context.close()


def test_composer_keyboard_counter_and_mobile_back(chat_browser):
    from playwright.sync_api import expect
    browser, origin = chat_browser
    context = browser.new_context(viewport={'width': 1280, 'height': 900})
    page = context.new_page()
    login(page, origin, 'alice')
    page.goto(origin + '/mensagens')
    page.locator('#chat-target').fill('BOB')
    page.get_by_role('button', name='Conversar', exact=True).click()
    expect(page.locator('[data-chat-sidebar]')).to_be_visible()
    body = page.locator('#chat-body')
    body.fill('Primeira linha')
    body.press('Shift+Enter')
    body.type('Segunda linha')
    expect(page.locator('[data-chat-counter]')).to_have_text('28 / 2000')
    expect(page.locator('.chat-message')).to_have_count(0)
    body.press('Enter')
    expect(page.locator('.chat-bubble p')).to_have_text('Primeira linha\nSegunda linha')
    expect(body).to_have_value('')
    expect(page.locator('[data-chat-counter]')).to_have_text('0 / 2000')
    page.set_viewport_size({'width': 390, 'height': 844})
    expect(page.locator('[data-chat-sidebar]')).not_to_be_visible()
    page.get_by_role('link', name='Todas as conversas', exact=True).click()
    expect(page.locator('[data-chat-sidebar]')).to_be_visible()
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    context.close()


def test_new_messages_stay_unread_until_reader_returns_to_bottom(chat_browser, app, monkeypatch):
    from playwright.sync_api import expect
    from test_chat import member, send, start
    from criticard.chat import views
    alice, token, conversation_id = start(app)
    app.config['CHAT_RATE_LIMIT'] = 100
    for index in range(24):
        assert send(alice, token, conversation_id, f'Parte {index}: ' + 'História para ler. ' * 8).status_code == 201
    browser, origin = chat_browser
    context = browser.new_context(viewport={'width': 1100, 'height': 820})
    page = context.new_page()
    login(page, origin, 'bob')
    page.goto(origin + f'/mensagens/{conversation_id}')
    expect(page.locator('[data-chat-status]')).to_have_text('Conectado')
    bob, bob_token = member(app, 2)
    page.wait_for_function("() => document.querySelector('[data-chat-read]').hidden")
    page.locator('[data-chat-messages]').evaluate('node => { node.scrollTop = 0; node.dispatchEvent(new Event("scroll")); }')
    assert send(bob, bob_token, conversation_id, 'Minha mensagem enviada por outra aba').status_code == 201
    expect(page.locator('.chat-bubble p').last).to_have_text('Minha mensagem enviada por outra aba')
    assert page.locator('[data-chat-messages]').evaluate('node => node.scrollTop') < 90
    original_publish = views.publish_message
    held = []

    def publish_out_of_order(message):
        if not held:
            held.append(message)
        else:
            original_publish(message)
            original_publish(held[0])

    monkeypatch.setattr(views, 'publish_message', publish_out_of_order)
    assert send(alice, token, conversation_id, 'Primeira mensagem entregue depois da segunda').status_code == 201
    assert send(alice, token, conversation_id, 'Nova mensagem enquanto você lê o início').status_code == 201
    expect(page.locator('.chat-message')).to_have_count(27)
    expect(page.locator('.chat-bubble p').last).to_have_text('Nova mensagem enquanto você lê o início')
    expect(page.locator('[data-chat-new-messages]')).to_be_visible()
    expect(page.locator('[data-chat-row-unread]')).to_have_text('2')
    assert bob.get('/mensagens', headers={'Accept': 'application/json'}).json['unread_count'] == 2
    page.locator('[data-chat-new-messages]').click()
    expect(page.locator('[data-chat-new-messages]')).not_to_be_visible()
    page.wait_for_function("() => document.querySelector('[data-chat-read]').hidden")
    # The read request is awaited by the control, so its completed UI state is proof.
    assert bob.get('/mensagens', headers={'Accept': 'application/json'}).json['unread_count'] == 0
    context.close()


def test_contact_finder_chooses_a_name_by_keyboard_and_escapes(chat_browser, app):
    from playwright.sync_api import expect
    from sqlalchemy import update
    from criticard.db import get_db
    from criticard.models import User
    with app.app_context():
        with get_db() as db:
            db.execute(update(User).where(User.id == 2).values(nome='Roberto Silva'))
    browser, origin = chat_browser
    context = browser.new_context(viewport={'width': 1280, 'height': 900})
    page = context.new_page()
    login(page, origin, 'alice')
    page.goto(origin + '/mensagens')
    field = page.locator('#chat-target')
    field.fill('Roberto')
    expect(page.get_by_role('option', name='Roberto Silva @BOB')).to_be_visible()
    field.press('Escape')
    expect(page.locator('[data-chat-contact-results]')).not_to_be_visible()
    expect(field).to_be_focused()
    field.fill('Roberto S')
    expect(page.get_by_role('option', name='Roberto Silva @BOB')).to_be_visible()
    field.press('ArrowDown')
    field.press('Enter')
    expect(field).to_have_value('@BOB')
    field.fill('Leitor')
    expect(page.get_by_role('option')).to_have_count(2)
    expect(page.get_by_role('option').last).to_have_accessible_name('Roberto Silva @BOB')
    field.press('ArrowUp')
    field.press('Enter')
    expect(field).to_have_value('@BOB')
    page.get_by_role('button', name='Conversar', exact=True).click()
    expect(page.get_by_role('heading', name='Roberto Silva', exact=True)).to_be_visible()
    context.close()


@pytest.mark.parametrize('scroll_away', [False, True])
def test_message_during_a_read_acknowledgement_gets_a_followup_receipt(chat_browser, app, monkeypatch, scroll_away):
    from playwright.sync_api import expect
    from threading import Event
    from criticard.chat import service
    from test_chat import member, send, start
    alice, token, conversation_id = start(app)
    for index in range(24):
        assert send(alice, token, conversation_id, f'Parte {index}: ' + 'Um trecho da nossa conversa. ' * 8).status_code == 201
    ack_pending, release_ack = Event(), Event()
    original_read = service.mark_read

    def delayed_read(user_id, target_conversation, message_id):
        result = original_read(user_id, target_conversation, message_id)
        if user_id == 2 and not ack_pending.is_set():
            ack_pending.set()
            release_ack.wait(timeout=8)
        return result

    monkeypatch.setattr(service, 'mark_read', delayed_read)
    browser, origin = chat_browser
    context = browser.new_context(viewport={'width': 1100, 'height': 820})
    page = context.new_page()
    try:
        login(page, origin, 'bob')
        page.goto(origin + f'/mensagens/{conversation_id}')
        assert ack_pending.wait(timeout=5)
        if scroll_away:
            page.locator('[data-chat-messages]').evaluate('node => { node.scrollTop = 0; node.dispatchEvent(new Event("scroll")); }')
        assert send(alice, token, conversation_id, 'Chegou antes da confirmação de leitura').status_code == 201
        expect(page.locator('.chat-bubble p').last).to_have_text('Chegou antes da confirmação de leitura')
        release_ack.set()
        bob, _ = member(app, 2)
        if scroll_away:
            expect(page.locator('[data-chat-row-unread]')).to_have_text('1')
            expect(page.locator('[data-chat-total-unread]')).to_have_text('1')
            assert bob.get('/mensagens', headers={'Accept': 'application/json'}).json['unread_count'] == 1
            page.locator('[data-chat-new-messages]').click()
        expect(page.locator('[data-chat-row-unread]')).to_have_count(0)
        assert bob.get('/mensagens', headers={'Accept': 'application/json'}).json['unread_count'] == 0
    finally:
        release_ack.set()
        context.close()
