"""Invitations, personal lists and accessible mobile navigation, isolated from real users."""
import os
import re

import pytest

from test_chat import app, action, member
from test_browser_chat import chat_browser, login

pytestmark = pytest.mark.skipif(os.getenv('CRITICARD_BROWSER_TESTS') != '1', reason='Optional browser regressions')


def test_invitation_acceptance_lists_and_follow_are_separate(chat_browser):
    from playwright.sync_api import expect
    browser, origin = chat_browser
    alice_context = browser.new_context(reduced_motion='reduce')
    bob_context = browser.new_context(viewport={'width': 390, 'height': 844}, reduced_motion='reduce')
    alice, bob = alice_context.new_page(), bob_context.new_page()
    errors = []
    for page in (alice, bob):
        page.on('pageerror', lambda error: errors.append(str(error)))
    login(alice, origin, 'alice')
    login(bob, origin, 'bob')
    alice.goto(origin + '/perfil/BOB')
    alice.locator('[data-friend-action="request"]').click()
    expect(alice.locator('[data-friendship-state]')).to_have_attribute('data-friendship-state', 'outgoing')
    alice.goto(origin + '/conexoes?aba=enviadas')
    expect(alice.locator('[data-connection-row="2"]')).to_contain_text('Solicitação enviada')
    bob.goto(origin + '/conexoes?aba=recebidas')
    expect(bob.locator('.site-header [data-unread-count]')).to_have_text('1')
    bob.locator('[data-connection-row="1"] [data-friend-action="accept"]').click()
    expect(bob.locator('[data-connection-row="1"]')).to_have_count(0)
    expect(bob.locator('[data-connections-status]')).to_contain_text('Amizade aceita')
    expect(bob.locator('.site-header [data-unread-count]')).to_have_text('0')
    bob.locator('.section-disclosure > summary').click()
    bob.locator('.connections-nav').get_by_role('link', name='Amigos', exact=False).click()
    expect(bob.locator('[data-connection-row="1"]')).to_contain_text('Conversar')
    alice.goto(origin + '/perfil/BOB')
    expect(alice.locator('[data-friendship-state]')).to_have_attribute('data-friendship-state', 'friends')
    expect(alice.locator('[data-follow-button]')).to_have_attribute('aria-pressed', 'false')
    alice.locator('[data-follow-button]').click()
    expect(alice.locator('[data-follow-button]')).to_have_attribute('aria-pressed', 'true')
    alice.goto(origin + '/conexoes?aba=seguindo')
    expect(alice.locator('[data-connection-row="2"]')).to_contain_text('Bob')
    alice.locator('#connections-search').fill('does-not-exist')
    alice.get_by_role('button', name='Buscar pessoas', exact=True).click()
    expect(alice.get_by_text('Nenhuma pessoa encontrada.', exact=True)).to_be_visible()
    assert bob.evaluate('document.documentElement.scrollWidth <= innerWidth')
    assert not errors
    alice_context.close()
    bob_context.close()


def test_connections_decline_cancel_and_forms_without_javascript(chat_browser):
    from playwright.sync_api import expect
    browser, origin = chat_browser
    context = browser.new_context(java_script_enabled=False, viewport={'width': 375, 'height': 812})
    page = context.new_page()
    login(page, origin, 'alice')
    page.goto(origin + '/conexoes?aba=descobrir')
    page.locator('[data-connection-row="2"] [data-friend-action="request"]').click()
    page.wait_for_url('**/conexoes?aba=descobrir')
    page.goto(origin + '/solicitacoes')
    expect(page.get_by_role('heading', name='Solicitações recebidas')).to_be_visible()
    assert not page.locator('.section-disclosure').evaluate('node => node.open')
    page.locator('.section-disclosure > summary').click()
    page.locator('.connections-nav').get_by_role('link', name='Enviadas', exact=False).click()
    page.locator('[data-connection-row="2"] [data-friend-action="cancel"]').click()
    page.wait_for_url('**/conexoes?aba=enviadas')
    expect(page.locator('[data-connection-row="2"]')).to_have_count(0)
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    context.close()


def test_last_page_mutation_keeps_query_and_updates_the_url(chat_browser, app):
    from playwright.sync_api import expect
    from test_connections_http import seed_outgoing_pages
    seed_outgoing_pages(app)
    browser, origin = chat_browser
    context = browser.new_context(reduced_motion='reduce')
    page = context.new_page()
    login(page, origin, 'alice')
    page.goto(origin + '/conexoes?aba=enviadas&q=Pessoa&page=2')
    expect(page.locator('[data-connection-row]')).to_have_count(1)
    page.locator('[data-friend-action="cancel"]').click()
    expect(page).to_have_url(re.compile(r'page=1'))
    assert 'q=Pessoa' in page.url
    expect(page.locator('[data-connection-row]')).to_have_count(24)
    expect(page.locator('#connections-title')).to_be_focused()
    context.close()


def test_delayed_friendship_refresh_cannot_revert_a_new_follow(chat_browser):
    from playwright.sync_api import expect
    browser, origin = chat_browser
    context = browser.new_context(reduced_motion='reduce')
    page = context.new_page()
    login(page, origin, 'alice')
    page.goto(origin + '/perfil/BOB')
    held = []
    def delay_first_refresh(route):
        if not held:
            # Reserve the delayed request before fetch pumps browser events.
            # Otherwise a second GET can enter this handler and also be held.
            held.append((route, None))
            held[0] = (route, route.fetch())
            page.evaluate('window.friendshipSnapshotCaptured = true')
        else:
            route.continue_()
    page.route('**/perfil/BOB', delay_first_refresh)
    with page.expect_request(lambda request: request.url == origin + '/perfil/BOB' and request.method == 'GET'):
        page.locator('[data-friend-action="request"]').click()
    page.wait_for_function('() => window.friendshipSnapshotCaptured === true')
    page.locator('[data-follow-button]').click()
    expect(page.locator('[data-follow-button]')).to_have_attribute('aria-pressed', 'true')
    assert len(held) == 1
    with page.expect_response(lambda response: response.url == origin + '/perfil/BOB'):
        held[0][0].fulfill(response=held[0][1])
    expect(page.locator('[data-connections-status]')).to_have_text('Solicitação enviada.')
    expect(page.locator('[data-friendship-state]')).to_have_attribute('data-friendship-state', 'outgoing')
    expect(page.locator('[data-follow-button]')).to_have_attribute('aria-pressed', 'true')
    assert page.locator('input[name="following"]').input_value() == 'false'
    context.close()
