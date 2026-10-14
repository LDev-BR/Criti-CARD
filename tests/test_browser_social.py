"""Optional Playwright social flows using isolated SQLite, uploads and server.

Browser plugin not available; reuse the repository's Playwright/Edge workflow.
Enable with CRITICARD_BROWSER_TESTS=1 and pytest tests/test_browser_social.py.
"""
import os

import pytest

from test_browser_forms import origin
from test_browser_reading import reading_page as social_page
from test_social import action, app, authenticated

pytestmark = pytest.mark.skipif(os.getenv('CRITICARD_BROWSER_TESTS') != '1', reason='Optional browser regressions')


def login(page, base, username='bob'):
    page.goto(base + '/')
    page.locator('#username').fill(username + '@example.com')
    page.locator('#senha').fill('Password1!')
    page.locator('.form-submit').click()
    page.wait_for_url('**/dashboard')


@pytest.mark.parametrize('width', [1280, 390])
def test_like_and_comment_update_without_reload_escape_text_and_keep_layout(social_page, width, tmp_path):
    page = social_page
    base = origin(page)
    login(page, base)
    page.set_viewport_size({'width': width, 'height': 844})
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto(base + '/social/cards/1/comments')
    assert 'Comentários' in page.title()
    assert page.locator('h1').inner_text()
    page.locator('[data-social-form="like"] button').click()
    pressed = page.locator('[data-social-form="like"] button[aria-pressed="true"]')
    pressed.wait_for()
    assert page.locator('[data-like-count]').inner_text() == '1'
    assert page.url == base + '/social/cards/1/comments'
    page.locator('#comment-body').fill('<img src=x onerror=alert(1)> Gostei!')
    page.locator('[data-social-form="comment"] button').click()
    page.locator('[data-comment-body]').filter(has_text='Gostei!').wait_for()
    assert page.locator('[data-comment-body] img').count() == 0
    assert page.locator('[data-comment-total]').inner_text() == '1'
    assert page.locator('#comment-body').input_value() == ''
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    assert not errors
    page.screenshot(path=str(tmp_path / f'social-{width}.png'), full_page=True)


def test_notifications_and_follow_block_actions(social_page, app):
    page = social_page
    base = origin(page)
    bob, token = authenticated(app, 2)
    assert action(bob, token, '/social/cards/1/like', method='put').status_code == 200
    login(page, base, 'alice')
    page.goto(base + '/social/notifications')
    assert page.locator('[data-notification-id].is-unread').count() == 1
    page.locator('[data-social-form="read"] button').click()
    page.locator('[data-notification-id].is-unread').wait_for(state='detached')
    assert page.locator('.social-page [data-unread-count]').inner_text() == '0'
    page.goto(base + '/perfil/BOB')
    page.locator('[data-follow-button]').click()
    page.locator('[data-follow-button][aria-pressed="true"]').wait_for()
    assert page.locator('[data-follower-count]').inner_text() == '1'
    page.get_by_role('button', name='Mais opções do perfil de @BOB').click()
    page.locator('[data-block-button]').click()
    page.get_by_role('button', name='Desbloquear', exact=True).wait_for()
    assert page.locator('[data-follow-button]').is_disabled()
    assert page.locator('[data-follower-count]').inner_text() == '0'


def test_social_forms_without_javascript(social_page):
    base = origin(social_page)
    page = social_page.context.browser.new_page(java_script_enabled=False, viewport={'width': 390, 'height': 844})
    try:
        login(page, base)
        page.goto(base + '/social/cards/1/comments')
        page.locator('[data-social-form="like"] button').click()
        page.wait_for_url('**/card/1')
        page.goto(base + '/social/cards/1/comments')
        assert page.locator('[data-like-count]').inner_text() == '1'
        page.locator('#comment-body').fill('Uma conversa sem JavaScript.')
        page.locator('[data-social-form="comment"] button').click()
        page.wait_for_url('**/social/cards/1/comments')
        assert page.locator('[data-comment-body]').inner_text() == 'Uma conversa sem JavaScript.'
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    finally:
        page.close()
