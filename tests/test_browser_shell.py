import os

import pytest

from criticard.db import get_db
from test_browser_reading import reading_page as shell_page
from test_browser_forms import origin, sign_in

pytestmark = pytest.mark.skipif(os.getenv('CRITICARD_BROWSER_TESTS') != '1', reason='Optional browser regressions')


def seed_reviews(app):
    with app.app_context():
        db = get_db()
        for title, score, author in [('Berserk',100,2), ('Berserk',75,3), ('Duna',95,2)]:
            work = db.execute('SELECT id FROM obras WHERE titulo=?', (title,)).fetchone()[0]
            db.execute('INSERT INTO cards (titulo,capa,sobre,nota,author_id,obra_id) VALUES (?,?,?,?,?,?)',
                       (title,'legacy.png','Uma boa história',score,author,work))
        db.commit()


def test_category_filter_search_reset_and_footer_navigation(shell_page, app):
    from playwright.sync_api import expect
    page = shell_page
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    seed_reviews(app)
    page.goto(origin(page) + '/criticas')
    page.locator('.category-tabs').get_by_role('link',name='Mangás',exact=True).click()
    expect(page.locator('[data-review-card]')).to_have_count(2)
    page.locator('#filter-minimum').fill('90')
    page.locator('#filter-sort').select_option('highest')
    page.locator('.filter-apply').click()
    expect(page.locator('[data-review-card]')).to_have_count(1)
    assert page.locator('[data-review-card]').get_attribute('data-score') == '100'
    page.locator('#q').fill('Bob')
    page.locator('.search-submit').click()
    expect(page.locator('[data-review-card]')).to_have_count(1)
    assert page.locator('#filter-minimum').input_value() == '90'
    assert page.locator('.category-tabs [aria-current]').inner_text() == 'Mangás'
    page.locator('.clear-filters').click()
    expect(page.locator('[data-review-card]')).to_have_count(4)
    page.locator('.footer-column').first.locator('summary').click()
    page.locator('.footer-categories').get_by_role('link',name='Livros',exact=True).click()
    expect(page.locator('[data-review-card]')).to_have_count(1)
    assert page.locator('[data-review-card]').get_attribute('data-title') == 'Duna'
    assert not errors


def test_mobile_menu_account_escape_support_and_logout(shell_page):
    page = shell_page
    sign_in(page)
    page.set_viewport_size({'width':390,'height':844})
    page.goto(origin(page) + '/feed')
    assert not page.locator('#primary-nav').is_visible()
    page.locator('[data-nav-toggle]').click()
    assert page.locator('#primary-nav').is_visible()
    assert page.locator('[data-nav-toggle]').get_attribute('aria-expanded') == 'true'
    page.locator('[data-account-menu] summary').click()
    assert page.locator('.account-panel').is_visible()
    page.keyboard.press('Escape')
    assert not page.locator('.account-panel').is_visible()
    page.keyboard.press('Escape')
    assert not page.locator('#primary-nav').is_visible()
    assert page.locator('[data-nav-toggle]').evaluate('node => node === document.activeElement')
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    page.locator('.footer-column').last.locator('summary').click()
    page.locator('.footer-links').get_by_role('link',name='Falar com o suporte',exact=True).click()
    page.locator('#suporte[open]').wait_for(state='visible')
    assert page.locator('#suporte').get_attribute('open') is not None
    page.locator('[data-nav-toggle]').click()
    page.locator('[data-account-menu] summary').click()
    page.locator('.account-logout button').click()
    page.wait_for_url(origin(page) + '/')
    assert page.locator('[data-account-menu]').count() == 0


def test_navigation_and_filters_without_javascript(shell_page, app):
    seed_reviews(app)
    page = shell_page.context.browser.new_page(java_script_enabled=False,viewport={'width':375,'height':812})
    try:
        page.goto(origin(shell_page) + '/criticas')
        assert not page.locator('#primary-nav').is_visible()
        assert page.locator('[data-nav-toggle]').is_visible()
        page.locator('[data-nav-toggle]').click()
        assert page.locator('#primary-nav').is_visible()
        page.locator('[data-nav-toggle]').click()
        page.locator('.filter-disclosure > summary').click()
        page.locator('.category-tabs').get_by_role('link',name='Mangás',exact=True).click()
        page.locator('#filter-minimum').fill('90')
        page.locator('.filter-apply').click()
        assert page.locator('[data-review-card]').count() == 1
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    finally:
        page.close()
