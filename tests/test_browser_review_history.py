"""Private review history and compact profiles remain usable without scripts."""
import json
import os
from pathlib import Path

import pytest
from sqlalchemy import insert, update

from criticard.config import ROOT
from criticard.db import get_db
from criticard.models import Card, User
from test_browser_forms import origin, sign_in
from test_browser_reading import reading_page as history_page

pytestmark = pytest.mark.skipif(os.getenv('CRITICARD_BROWSER_TESTS') != '1', reason='Optional Edge checks')


def test_history_is_private_and_long_profile_does_not_push_reviews_out_of_view(history_page, app):
    from playwright.sync_api import expect
    with app.app_context():
        with get_db() as db:
            db.execute(update(User).where(User.id == 1).values(about='Minha história pública. ' * 60))
            db.execute(insert(Card).values(id=2, author_id=1, obra_id=26, archived=1,
                titulo='Berserk: crítica anterior', capa='catalog:mangas:0', sobre='Experiência preservada.', nota=80))
            db.execute(insert(Card).values(id=3, author_id=1, obra_id=26,
                titulo='Berserk', capa='catalog:mangas:0', sobre='Experiência atualizada.', nota=100))
    base = origin(history_page)
    artifacts = ROOT / '.runtime/responsive-history-qa'
    artifacts.mkdir(parents=True, exist_ok=True)
    context = history_page.context.browser.new_context(java_script_enabled=False, bypass_csp=True,
        viewport={'width':360, 'height':800}, reduced_motion='reduce')
    page = context.new_page()
    report = []
    try:
        page.goto(base + '/')
        sign_in(page)
        page.goto(base + '/dashboard')
        expect(page.locator('#card-2')).to_have_count(0)
        expect(page.locator('#card-3')).to_be_visible()
        assert page.locator('#card-3').bounding_box()['y'] < 800
        expect(page.locator('.profile-about')).not_to_have_attribute('open')
        page.locator('.profile-about > summary').click()
        expect(page.locator('.profile-bio')).to_contain_text('Minha história pública.')
        page.locator('.profile-about > summary').click()
        page.get_by_role('link', name='Histórico privado (1)', exact=True).click()
        expect(page.locator('#card-2')).to_be_visible()
        expect(page.locator('#card-3')).to_have_count(0)
        page.locator('#card-2').get_by_role('link', name='Ler crítica', exact=True).click()
        expect(page.get_by_text('Experiência preservada.', exact=True)).to_be_visible()
        expect(page.locator('[data-social-form]')).to_have_count(0)
        # Keep the interaction flow above fully scriptless. Axe needs timers,
        # so audit the same synthetic owner's screen in a separate context.
        audit_context = context.browser.new_context(bypass_csp=True, storage_state=context.storage_state(),
            viewport={'width':360,'height':800}, reduced_motion='reduce')
        try:
            audited = audit_context.new_page()
            audited.goto(base + '/card/2')
            for width in (360, 768, 1280):
                audited.set_viewport_size({'width':width, 'height':800})
                audited.evaluate('window.scrollTo(0,0)')
                assert audited.evaluate('document.documentElement.scrollWidth <= innerWidth')
                audited.screenshot(path=str(artifacts / f'history-{width}.png'), full_page=True)
                audited.add_script_tag(path=str(ROOT / 'node_modules/axe-core/axe.min.js'))
                violations = audited.evaluate("async () => (await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']}})).violations.map(v=>v.id)")
                report.append({'width':width,'violations':violations})
        finally:
            audit_context.close()
        guest = context.browser.new_context(java_script_enabled=False, viewport={'width':360,'height':800})
        try:
            visitor = guest.new_page()
            assert visitor.goto(base + '/card/2').status == 404
            visitor.goto(base + '/perfil/ALICE')
            expect(visitor.locator('#card-2')).to_have_count(0)
            assert visitor.locator('#card-3').bounding_box()['y'] < 800
            visitor.locator('.profile-about > summary').click()
            expect(visitor.locator('.profile-bio')).to_contain_text('Minha história pública.')
        finally:
            guest.close()
        (artifacts / 'axe.json').write_text(json.dumps(report), encoding='utf-8')
        assert not [state for state in report if state['violations']]
    finally:
        context.close()
