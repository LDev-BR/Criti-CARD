"""Journey verification against synthetic accounts on an isolated live server."""
import os
import json
import tempfile
from pathlib import Path

import pytest

from test_browser_reading import reading_page
from test_browser_forms import origin, sign_in
from criticard.config import ROOT
from criticard.db import get_db
from criticard.models import utcnow
from criticard.progression.service import record_action, record_event
from criticard.settings.service import get_preferences, save_preferences

pytestmark = pytest.mark.skipif(os.getenv('CRITICARD_BROWSER_TESTS')!='1',reason='Enable isolated Playwright browser tests')


def seed_apprentice_history(db, now):
    # Import 970 XP without consuming the live quota or the next three reviews.
    # Their 40 XP awards plus weekly participation cross the 1,100 XP tier.
    for work_id in range(4, 23):
        record_event(db, 1, 'card_published', f'card:{work_id}', now,
                     work_id=work_id, category_id=1, origin='history')
    for work_id in range(1, 15):
        record_event(db, 1, 'work_completed', f'completed:{work_id}', now,
                     work_id=work_id, category_id=1, origin='history')


def test_cosmetic_frames_preserve_card_and_avatar_dimensions(reading_page):
    page = reading_page
    card = page.locator('#card-1')
    avatar = card.locator('.reward-avatar')
    dimensions = lambda node: node.evaluate('el => ({width:el.getBoundingClientRect().width,height:el.getBoundingClientRect().height})')
    initial, initial_avatar = dimensions(card), dimensions(avatar)
    for material in ('classic','slate','bronze','copper','silver','sapphire','gold','platinum','obsidian','obsidian_gold'):
        card.evaluate('(el,value) => el.dataset.cardStyle=value','card_'+material)
        avatar.evaluate('(el,value) => el.dataset.avatarStyle=value','frame_'+material)
        assert dimensions(card)==initial
        assert dimensions(avatar)==initial_avatar


def test_journey_controls_and_mobile_layout(reading_page):
    page = reading_page
    errors = []
    page.on('pageerror',lambda error:errors.append(str(error)))
    sign_in(page)
    for width in (360,768,1280):
        page.set_viewport_size(dict(width=width,height=900))
        page.goto(origin(page)+'/jornada',wait_until='networkidle')
        assert 'Minha jornada' in page.title()
        assert page.locator('[data-progression-summary]').is_visible()
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    page.locator('#conquistas > summary').click()
    assert page.locator('[data-achievement]:visible').count()==6
    page.locator('[data-achievements-next]').click()
    assert page.locator('[data-achievements-page]').inner_text().startswith('2 /')
    assert not errors


def publish(page,work_id):
    page.goto(origin(page)+'/cadastro_cards')
    page.locator('#obra_id').select_option(str(work_id))
    page.locator('#nota').fill('90')
    page.locator('#sobre').fill('Uma obra memorável. O ritmo e os personagens ficam comigo.')
    page.locator('.form-submit').click()
    page.wait_for_url('**/dashboard')


def test_publish_unlock_equip_public_profile_composer_and_optout(reading_page,app):
    from playwright.sync_api import expect
    with app.app_context():
        with get_db() as db:
            seed_apprentice_history(db, utcnow())
    page = reading_page
    sign_in(page)
    publish(page,1)
    expect(page.locator('[data-level]')).to_have_text('10')
    assert page.locator('.flashes').inner_text().count('Jornada: nível')==1
    page.reload()
    assert page.locator('.flashes').count()==0
    page.goto(origin(page)+'/jornada',wait_until='networkidle')
    assert page.locator('#reward-frame option[value="frame_slate"]').is_disabled()
    page.locator('#reward-badge').select_option('badge_level_005')
    page.locator('[data-reward-form] button[type=submit]').click()
    expect(page.locator('[data-reward-status]')).to_have_text('Personalização salva.')
    publish(page,2)
    publish(page,3)
    page.goto(origin(page)+'/jornada',wait_until='networkidle')
    assert not page.locator('#reward-frame option[value="frame_slate"]').is_disabled()
    page.locator('#reward-frame').select_option('frame_slate')
    page.locator('#reward-card').select_option('card_slate')
    page.locator('[name=progression_public]').check()
    page.locator('[data-reward-form] button[type=submit]').click()
    expect(page.locator('[data-reward-status]')).to_have_text('Personalização salva.')
    page.goto(origin(page)+'/perfil/ALICE')
    expect(page.locator('[data-progression-badge]')).to_contain_text('Nível 11')
    assert page.locator('[data-card-style=card_slate]').count()==4
    page.goto(origin(page)+'/cadastro_cards')
    expect(page.locator('.draft-card')).to_have_attribute('data-card-style','card_slate')
    page.goto(origin(page)+'/criticas')
    page.locator('#q').fill('Alice')
    expect(page.locator('[data-live-status]')).to_contain_text('resultado')
    assert page.locator('[data-card-style=card_slate]').count()==4
    other = page.context.browser.new_page()
    try:
        other.goto(origin(page)+'/')
        other.locator('#username').fill('bob')
        other.locator('#senha').fill('Password1!')
        other.locator('.form-submit').click()
        other.wait_for_url('**/dashboard')
        other.goto(origin(page)+'/perfil/ALICE')
        assert other.locator('#extrato').count()==0
        assert other.request.get(origin(page)+'/jornada?user_id=1').status==404
    finally:
        other.close()
    page.goto(origin(page)+'/jornada',wait_until='networkidle')
    page.locator('[name=progression_public]').uncheck()
    page.locator('[data-reward-form] button[type=submit]').click()
    expect(page.locator('[data-reward-status]')).to_have_text('Personalização salva.')
    page.goto(origin(page)+'/perfil/ALICE')
    assert page.locator('[data-progression-badge]').count()==0
    assert page.locator('[data-card-style=card_classic]').count()==4


def test_rewards_handle_network_failure_and_edits_during_save(reading_page,app):
    from playwright.sync_api import expect
    with app.app_context():
        with get_db() as db:
            seed_apprentice_history(db, utcnow())
            for n in (1,2,3):
                record_action(db,1,'card_published',utcnow(),work_id=n,category_id=1)
    page = reading_page
    sign_in(page)
    page.goto(origin(page)+'/jornada',wait_until='networkidle')
    page.route('**/jornada/personalizar',lambda route:route.abort())
    page.locator('#reward-frame').select_option('frame_slate')
    page.locator('[data-reward-form] button[type=submit]').click()
    expect(page.locator('[data-reward-status]')).to_contain_text('foram mantidas')
    assert page.locator('#reward-frame').input_value()=='frame_slate'
    page.unroute('**/jornada/personalizar')
    held = []
    def hold(route):
        held.append((route,route.fetch()))
        page.evaluate('window.rewardSaveHeld = true')
    page.route('**/jornada/personalizar',hold)
    page.locator('[data-reward-form] button[type=submit]').click()
    expect(page.locator('[data-reward-status]')).to_have_text('Salvando…')
    page.wait_for_function('() => window.rewardSaveHeld === true')
    page.locator('#reward-frame').select_option('frame_classic')
    assert len(held)==1
    held[0][0].fulfill(response=held[0][1])
    expect(page.locator('[data-reward-status]')).to_contain_text('últimas escolhas')
    assert page.locator('#reward-frame').input_value()=='frame_classic'
    page.unroute('**/jornada/personalizar')
    page.locator('[data-reward-form] button[type=submit]').click()
    expect(page.locator('[data-reward-status]')).to_have_text('Personalização salva.')
    with app.app_context():
        assert get_preferences(1)['progression_frame']=='frame_classic'


def test_journey_without_javascript_and_ledger_pagination(reading_page,app):
    from datetime import timedelta
    with app.app_context():
        with get_db() as db:
            for n in range(1,25):
                record_action(db,1,'card_published',utcnow()-timedelta(days=25-n),work_id=n,category_id=1)
    page = reading_page.context.browser.new_page(java_script_enabled=False,viewport=dict(width=360,height=800))
    try:
        page.goto(origin(reading_page)+'/')
        sign_in(page)
        page.goto(origin(page)+'/jornada')
        page.locator('#reward-badge').select_option('badge_level_005')
        page.locator('[data-reward-form] button[type=submit]').click()
        page.wait_for_url('**/jornada#personalizar')
        page.goto(origin(page)+'/jornada?conquistas=unlocked#conquistas')
        assert page.locator('[data-achievement]').count()>1
        assert page.locator('[data-achievement]:not(.is-unlocked)').count()==0
        page.goto(origin(page)+'/jornada#extrato')
        page.locator('#extrato > summary').click()
        assert page.locator('.xp-events li').count()==20
        page.locator('.event-pagination').get_by_role('link',name='Próxima').click()
        page.wait_for_url('**/jornada?page=2&conquistas=all#extrato')
        assert page.locator('#extrato').evaluate('el=>el.open')
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        with app.app_context():
            assert get_preferences(1)['progression_notices'] is True
    finally:
        page.close()


def test_journey_accessibility_keyboard_and_screenshots(reading_page,app):
    from playwright.sync_api import expect
    with app.app_context():
        save_preferences(1,'aparencia',{'reduce_motion':True,'high_contrast':True,'text_size':'large'})
        with get_db() as db:
            seed_apprentice_history(db, utcnow())
            for n in (1,2,3):
                record_action(db,1,'card_published',utcnow(),work_id=n,category_id=1)
    artifacts = Path(tempfile.mkdtemp(prefix='criticard-progression-'))
    errors, report = [], []
    for width in (360,768,1280):
        context = reading_page.context.browser.new_context(bypass_csp=True,reduced_motion='reduce',viewport=dict(width=width,height=900))
        page = context.new_page()
        page.on('pageerror',lambda error:errors.append(str(error)))
        page.on('console',lambda message: errors.append(message.text) if message.type in ('error','warning') else None)
        try:
            page.goto(origin(reading_page)+'/')
            sign_in(page)
            page.goto(origin(page)+'/jornada',wait_until='networkidle')
            page.locator('#reward-frame').focus()
            expect(page.locator('#reward-frame')).to_be_focused()
            page.keyboard.press('ArrowDown')
            assert page.locator('#reward-frame').input_value()=='frame_slate'
            page.keyboard.press('Tab')
            expect(page.locator('#reward-card')).to_be_focused()
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            page.evaluate('scrollTo(0,0)')
            page.screenshot(path=str(artifacts/f'journey-{width}.png'),animations='disabled')
            page.add_script_tag(path=str(ROOT/'node_modules/axe-core/axe.min.js'))
            violations = page.evaluate("async()=> (await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa','best-practice']}})).violations.map(v=>({id:v.id,impact:v.impact,nodes:v.nodes.map(n=>n.target)}))")
            report.append(dict(width=width,violations=violations))
            assert not violations,report[-1]
            assert not errors,errors
        finally:
            context.close()
    (artifacts/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(f'Progression QA: {artifacts}; 360/768/1280, keyboard, reduced motion/high contrast/large text.')


def test_opening_journey_updates_age_progress_without_overwriting_form(reading_page,app):
    from datetime import timedelta
    from sqlalchemy import update
    from criticard.progression.models import ProgressionProfile
    from playwright.sync_api import expect
    page = reading_page
    sign_in(page)
    with app.app_context():
        with get_db() as db:
            db.execute(update(ProgressionProfile).where(ProgressionProfile.user_id==1)
                .values(membership_since=utcnow()-timedelta(days=91)))
    page.goto(origin(page)+'/jornada')
    expect(page.locator('[data-level]')).to_have_text('2')
    expect(page.locator('[data-journey-status]')).to_contain_text('Ver novos desbloqueios')
    assert page.locator('[data-reward-form]').is_visible()
