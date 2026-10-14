"""Live GET searches and collection writes against isolated server/database."""
import os
import json
import re
import tempfile
from pathlib import Path

import pytest

from criticard.backlog.service import add_item
from criticard.db import get_db
from test_browser_forms import origin, sign_in
from test_browser_reading import reading_page as live_page

pytestmark = pytest.mark.skipif(os.getenv('CRITICARD_BROWSER_TESTS') != '1', reason='Optional browser regressions')


def work_id(title):
    return str(get_db().execute('SELECT id FROM obras WHERE titulo=?', (title,)).fetchone()[0])


@pytest.mark.parametrize('route,control,query,rows', [
    ('/criticas', '#q', 'Alice', '[data-review-card]'),
    ('/catalogo', '#backlog-q', 'Hades', '[data-catalog-work]'),
    ('/backlog', '#backlog-q', 'Hades', '[data-backlog-item]'),
    ('/colecao/ALICE', '#backlog-q', 'Hades', '[data-backlog-item]'),
    ('/conexoes?aba=descobrir', '#connections-search', 'Bob', '[data-connection-row]'),
    ('/admin/obras', '#catalog-q', 'Hades', '[data-admin-work]'),
])
def test_live_search_preserves_document_focus_and_clear(live_page, app, route, control, query, rows):
    from playwright.sync_api import expect
    with app.app_context():
        add_item(1, {'obra_id': work_id('Hades'), 'visibility': 'public'})
    page = live_page
    if route.startswith('/admin'):
        page.goto(origin(page) + '/')
        page.locator('#username').fill('admin')
        page.locator('#senha').fill('Password1!')
        page.locator('.form-submit').click()
        page.wait_for_url('**/dashboard')
    else:
        sign_in(page)
    page.goto(origin(page) + route)
    page.evaluate('window.liveSearchDocument = 42')
    page.locator(control).evaluate('node => window.liveSearchInput = node')
    page.locator(control).fill(query)
    expect(page).to_have_url(re.compile('q=' + query))
    expect(page.locator(rows)).to_have_count(1)
    expect(page.locator(control)).to_be_focused()
    assert page.locator(control).evaluate('node => node === window.liveSearchInput')
    assert page.evaluate('window.liveSearchDocument') == 42
    page.locator(control).fill('no-such-result')
    expect(page.locator(rows)).to_have_count(0)
    expect(page.locator('[data-live-status]')).to_contain_text('Nenhum resultado')
    page.locator(control).fill('')
    expect(page.locator(rows).first).to_be_visible()
    assert page.evaluate('window.liveSearchDocument') == 42


def test_feed_cards_and_catalog_actions_work_after_search(live_page, app):
    from playwright.sync_api import expect
    page = live_page
    sign_in(page)
    page.goto(origin(page) + '/criticas')
    page.locator('#q').fill('Alice')
    expect(page.locator('[data-live-status]')).to_contain_text('resultado')
    page.locator('.read-review').click()
    expect(page.locator('[data-card-back]')).to_be_visible()
    page.locator('[data-expand-review]').click()
    expect(page.locator('#review-dialog')).to_be_visible()
    page.keyboard.press('Escape')
    page.goto(origin(page) + '/catalogo')
    page.locator('#backlog-q').fill('Hades')
    expect(page.locator('[data-catalog-work]')).to_have_count(1)
    page.locator('[data-backlog-add] button').click()
    expect(page.locator('[data-backlog-message]')).to_contain_text('adicionada')
    assert page.locator('[data-backlog-add] button').is_disabled()
    with app.app_context():
        assert get_db().execute('SELECT count(*) FROM backlog_items WHERE user_id=1').scalar() == 1


def test_loading_failure_retry_and_late_response(live_page):
    from playwright.sync_api import expect
    page = live_page
    page.goto(origin(page) + '/catalogo')
    page.route('**/catalogo?**', lambda route: route.abort())
    page.locator('#backlog-q').fill('Hades')
    expect(page.locator('[data-live-status]')).to_contain_text('Não foi possível')
    expect(page.locator('[data-catalog-work]')).to_have_count(30)
    assert page.locator('[data-live-search]').get_attribute('aria-busy') == 'false'
    page.unroute('**/catalogo?**')
    page.locator('[data-live-retry]').click()
    expect(page.locator('[data-catalog-work]')).to_have_count(1)
    page.locator('#backlog-q').fill('')
    expect(page.locator('[data-catalog-work]')).to_have_count(30)
    page.evaluate("""() => {
        const realFetch = window.fetch;
        window.fetch = async (...args) => {
            const response = await realFetch(...args);
            if (new URL(args[0], location.href).searchParams.get('q') === 'Hades') {
                const body = await response.text();
                window.oldSearchReady = true;
                await new Promise(resolve => window.releaseOldSearch = resolve);
                return new Response(body, {status: 200, headers: {'Content-Type': 'text/html'}});
            }
            return response;
        };
    }""")
    page.locator('#backlog-q').fill('Hades')
    page.wait_for_function('() => window.oldSearchReady === true')
    page.locator('#backlog-q').fill('Duna')
    expect(page.locator('.catalog-work h3')).to_have_text(['Duna'])
    page.evaluate('window.releaseOldSearch()')
    page.wait_for_timeout(100)
    expect(page.locator('.catalog-work h3')).to_have_text(['Duna'])
    expect(page.locator('#backlog-q')).to_have_value('Duna')


def test_history_filters_and_composition(live_page):
    from playwright.sync_api import expect
    page = live_page
    page.goto(origin(page) + '/catalogo')
    page.evaluate('window.liveSearchDocument = 42')
    page.locator('#backlog-category').select_option('livros')
    expect(page.locator('[data-catalog-work]')).to_have_count(5)
    expect(page).to_have_url(re.compile('categoria=livros'))
    page.locator('#backlog-q').focus()
    page.locator('#backlog-q').dispatch_event('compositionstart')
    page.locator('#backlog-q').fill('Duna')
    page.wait_for_timeout(400)
    expect(page.locator('[data-catalog-work]')).to_have_count(5)
    page.locator('#backlog-q').dispatch_event('compositionend')
    expect(page.locator('[data-catalog-work]')).to_have_count(1)
    page.go_back()
    expect(page.locator('[data-catalog-work]')).to_have_count(5)
    expect(page.locator('#backlog-q')).to_have_value('')
    assert page.evaluate('window.liveSearchDocument') == 42


def test_collection_save_and_remove_without_navigation(live_page, app):
    from playwright.sync_api import expect
    with app.app_context():
        add_item(1, {'obra_id': work_id('Hades')})
    page = live_page
    sign_in(page)
    page.goto(origin(page) + '/backlog')
    page.evaluate('window.liveSearchDocument = 42')
    page.locator('.backlog-edit summary').click()
    page.locator('[data-backlog-update] [name=status]').select_option('in_progress')
    page.locator('[data-backlog-update] [name=progress]').fill('12')
    page.locator('[data-backlog-update] [name=progress_unit]').select_option('hours')
    page.locator('[data-backlog-update] button').click()
    expect(page.locator('.backlog-status')).to_have_text('Jogando')
    expect(page.locator('.backlog-item-meta')).to_contain_text('12 horas')
    assert page.evaluate('window.liveSearchDocument') == 42
    page.locator('.backlog-edit summary').click()
    page.locator('.backlog-remove button').click()
    expect(page.locator('[data-backlog-item]')).to_have_count(0)
    assert page.evaluate('window.liveSearchDocument') == 42


def test_debounce_and_guest_search_without_javascript(live_page):
    from playwright.sync_api import expect
    page = live_page
    page.goto(origin(page) + '/catalogo')
    requests = []
    page.on('request', lambda request: requests.append(request.url)
            if '/catalogo?' in request.url else None)
    page.locator('#backlog-q').press_sequentially('Hades', delay=25)
    expect(page.locator('[data-catalog-work]')).to_have_count(1)
    assert len(requests) == 1
    context = page.context.browser.new_context(java_script_enabled=False, viewport={'width': 360, 'height': 800})
    native = context.new_page()
    try:
        native.goto(origin(page) + '/catalogo')
        native.locator('.backlog-filter-disclosure summary').click()
        native.locator('#backlog-q').fill('Duna')
        native.locator('.backlog-filters button').click()
        expect(native.locator('[data-catalog-work]')).to_have_count(1)
        expect(native.locator('.catalog-work h3')).to_have_text('Duna')
    finally:
        context.close()


def test_live_pagination_and_session_expiry_keep_valid_results(live_page, app):
    from playwright.sync_api import expect
    with app.app_context():
        with get_db() as db:
            for work in range(1, 14):
                db.execute('INSERT INTO cards(titulo,capa,sobre,nota,author_id,obra_id) VALUES(?,?,?,?,?,?)',
                           ('Crítica', 'legacy.png', 'Experiência memorável', 80, 2, work))
    page = live_page
    page.goto(origin(page) + '/criticas')
    page.evaluate('window.liveSearchDocument = 42')
    page.locator('.pagination').get_by_role('link', name='Próxima', exact=False).click()
    expect(page).to_have_url(re.compile('page=2'))
    expect(page.locator('[data-live-results-heading]')).to_be_focused()
    assert page.evaluate('window.liveSearchDocument') == 42
    page.locator('#q').fill('Alice')
    expect(page.locator('[data-review-card]')).to_have_count(1)
    assert 'page=' not in page.url
    sign_in(page)
    page.goto(origin(page) + '/conexoes?aba=descobrir')
    page.context.clear_cookies()
    page.locator('#connections-search').fill('Bob')
    expect(page.locator('[data-live-status]')).to_contain_text('sessão')
    expect(page.locator('[data-connection-row]')).to_have_count(2)
    expect(page.locator('#connections-search')).to_have_value('Bob')


def test_other_collection_draft_survives_save_and_filter(live_page, app):
    from playwright.sync_api import expect
    with app.app_context():
        add_item(1, {'obra_id': work_id('Hades')})
        add_item(1, {'obra_id': work_id('Elden Ring')})
    page = live_page
    sign_in(page)
    page.goto(origin(page) + '/backlog')
    first = page.locator('[data-backlog-item="1"]')
    other = page.locator('[data-backlog-item="2"]')
    first.locator('.backlog-edit summary').click()
    other.locator('.backlog-edit summary').click()
    other.locator('[name=progress]').fill('25')
    first.locator('[name=status]').select_option('completed')
    first.locator('[data-backlog-update] button').click()
    expect(first.locator('.backlog-status')).to_have_text('Jogado')
    expect(other.locator('[name=progress]')).to_have_value('25')
    page.locator('#backlog-q').fill('Hades')
    expect(page.locator('[data-backlog-item]')).to_have_count(1)
    page.locator('#backlog-q').fill('')
    expect(page.locator('[data-backlog-item]')).to_have_count(2)
    expect(other.locator('[name=progress]')).to_have_value('25')


def test_feed_typing_and_filtering_share_current_controls(live_page):
    from playwright.sync_api import expect
    page = live_page
    page.goto(origin(page) + '/criticas')
    page.locator('#q').fill('Alice')
    page.locator('#filter-sort').select_option('highest')
    expect(page).to_have_url(re.compile('q=Alice'))
    expect(page).to_have_url(re.compile('ordem=highest'))
    expect(page.locator('#q')).to_have_value('Alice')
    expect(page.locator('[data-review-card]')).to_have_count(1)
    page.goto(origin(page) + '/criticas')
    page.locator('#filter-sort').select_option('highest')
    page.locator('#q').fill('Alice')
    expect(page).to_have_url(re.compile('q=Alice'))
    expect(page).to_have_url(re.compile('ordem=highest'))
    expect(page.locator('#filter-sort')).to_have_value('highest')


def test_pending_save_freezes_its_form_and_commits_search_url(live_page, app):
    from playwright.sync_api import expect
    with app.app_context():
        add_item(1, {'obra_id': work_id('Hades')})
    page = live_page
    sign_in(page)
    page.goto(origin(page) + '/backlog')
    held = []
    def hold_save(route):
        held.append((route, route.fetch()))
        page.evaluate('window.backlogSaveHeld = true')
    page.route('**/backlog/*/update', hold_save)
    page.locator('.backlog-edit summary').click()
    page.locator('[data-backlog-update] [name=status]').select_option('completed')
    page.locator('[data-backlog-update] button').click()
    expect(page.locator('[data-backlog-update]')).to_have_js_property('inert', True)
    page.wait_for_function('() => window.backlogSaveHeld === true')
    assert len(held) == 1
    page.locator('#backlog-q').fill('Duna')
    held[0][0].fulfill(response=held[0][1])
    expect(page.locator('[data-backlog-item]')).to_have_count(0)
    expect(page).to_have_url(re.compile('q=Duna'))
    expect(page.locator('#backlog-q')).to_be_focused()
    page.locator('#backlog-q').fill('')
    expect(page.locator('.backlog-status')).to_have_text('Jogado')
    expect(page.locator('[data-backlog-update]')).to_have_js_property('inert', False)


def test_live_search_visual_accessibility_and_mobile(live_page, app):
    from playwright.sync_api import expect
    from criticard.config import ROOT
    with app.app_context():
        add_item(1, {'obra_id': work_id('Hades'), 'visibility': 'public'})
    artifacts = Path(tempfile.mkdtemp(prefix='criticard-live-search-'))
    report = []
    errors = []
    for width in (360, 768, 1280):
        context = live_page.context.browser.new_context(bypass_csp=True, reduced_motion='reduce',
            viewport={'width': width, 'height': 800})
        page = context.new_page()
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('console', lambda message: errors.append(message.text) if message.type in ('error', 'warning') else None)
        try:
            page.goto(origin(live_page) + '/')
            sign_in(page)
            for label, route, control, query in [
                ('reviews', '/criticas', '#q', 'Alice'),
                ('catalog', '/catalogo', '#backlog-q', 'Hades'),
                ('collection', '/backlog', '#backlog-q', 'Hades'),
                ('public-collection', '/colecao/ALICE', '#backlog-q', 'Hades'),
                ('connections', '/conexoes?aba=descobrir', '#connections-search', 'Bob'),
                ('admin', '/admin/obras', '#catalog-q', 'Hades'),
            ]:
                if label == 'admin':
                    context.clear_cookies()
                    page.goto(origin(live_page) + '/')
                    page.locator('#username').fill('admin')
                    page.locator('#senha').fill('Password1!')
                    page.locator('.form-submit').click()
                    page.wait_for_url('**/dashboard')
                page.goto(origin(live_page) + route)
                disclosure = page.locator('.backlog-filter-disclosure')
                if disclosure.count() and not disclosure.evaluate('node => node.open'):
                    disclosure.locator('summary').click()
                page.locator(control).fill(query)
                expect(page.locator('[data-live-status]')).to_contain_text('resultado')
                expect(page.locator(control)).to_be_focused()
                assert page.title() and page.locator('main').inner_text().strip()
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                page.evaluate('() => scrollTo(0, 0)')
                page.screenshot(path=str(artifacts / f'{label}-{width}.png'), animations='disabled')
                page.add_script_tag(path=str(ROOT / 'node_modules/axe-core/axe.min.js'))
                violations = page.evaluate("""async () => (await axe.run(document, {
                    runOnly: {type: 'tag', values: ['wcag2a','wcag2aa','wcag21aa','wcag22aa','best-practice']}
                })).violations.map(v => ({id: v.id, nodes: v.nodes.map(n => n.target)}))""")
                report.append({'screen': label, 'width': width, 'violations': violations})
                assert not violations, report[-1]
        finally:
            context.close()
    (artifacts / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    assert not errors, errors
    print(f'Live search QA: {artifacts}; 18 states; no axe/console/overflow findings.')
