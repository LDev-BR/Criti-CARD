"""Toast and notification behavior on a live, isolated application."""
import os
import re

import pytest

from conftest import post
from test_browser_reading import reading_page
from test_browser_forms import origin, sign_in
from test_notifications import notices

pytestmark = pytest.mark.skipif(os.getenv('CRITICARD_BROWSER_TESTS') != '1', reason='Enable isolated browser tests')


def toast(page, message, options=None):
    page.evaluate("async ({message, options}) => { const { toast } = await import('/static/toasts.js'); toast(message, options); }",
                  dict(message=message, options=options or {}))


def test_toasts_are_safe_dismissible_and_errors_stay_visible(reading_page):
    from playwright.sync_api import expect
    page = reading_page
    toast(page, '<img src=x onerror=alert(1)>', {'type': 'error', 'duration': 100})
    notice = page.locator('[data-toast]')
    expect(notice).to_contain_text('<img src=x onerror=alert(1)>')
    assert notice.locator('img').count() == 0
    # A caller-provided short duration must not auto-dismiss a critical error.
    page.wait_for_timeout(200)
    expect(notice).to_be_visible()
    notice.get_by_role('button', name='Fechar aviso').click()
    expect(notice).to_have_count(0)


def test_toast_queue_deduplicates_and_limits_visible_messages(reading_page):
    from playwright.sync_api import expect
    page = reading_page
    for message in ('Um', 'Dois', 'Três', 'Quatro', 'Quatro'):
        toast(page, message, {'type': 'info', 'duration': 0})
    expect(page.locator('[data-toast]')).to_have_count(3)
    page.locator('[data-toast]').first.get_by_role('button', name='Fechar aviso').click()
    expect(page.locator('[data-toast]')).to_have_count(3)
    expect(page.locator('[data-toast]').last).to_contain_text('Quatro')
    for _ in range(3):
        page.locator('[data-toast]').first.get_by_role('button', name='Fechar aviso').click()
    expect(page.locator('[data-toast]')).to_have_count(0)


def test_old_toast_handles_cannot_dismiss_a_recreated_notice(reading_page):
    from playwright.sync_api import expect
    page = reading_page
    page.evaluate("""async () => {
        const {toast} = await import('/static/toasts.js');
        window.oldNotice = toast('Mesmo aviso', {duration:0});
        window.duplicateNotice = toast('Mesmo aviso', {duration:0});
        oldNotice.dismiss();
        toast('Mesmo aviso', {duration:0});
        oldNotice.dismiss(); duplicateNotice.dismiss();
    }""")
    expect(page.locator('[data-toast]')).to_have_count(1)
    page.get_by_role('button',name='Fechar aviso').click()
    expect(page.locator('[data-toast]')).to_have_count(0)


def test_positive_toast_duration_keeps_six_second_reading_time(reading_page):
    from playwright.sync_api import expect
    page = reading_page
    page.clock.install()
    page.clock.pause_at(page.evaluate('Date.now()')+1000)
    toast(page,'Tempo para ler',{'type':'success','duration':1})
    page.clock.run_for(5999)
    expect(page.locator('[data-toast]')).to_have_count(1)
    page.clock.run_for(2)
    expect(page.locator('[data-toast]')).to_have_count(0)


@pytest.mark.parametrize('failed',[False,True])
def test_journey_sync_feedback_has_one_live_announcement(reading_page,failed):
    from playwright.sync_api import expect
    page = reading_page
    sign_in(page)
    page.route('**/jornada/sincronizar', lambda route:route.fulfill(
        status=503 if failed else 200,json={'notice':'Novos marcos disponíveis.'}))
    page.goto(origin(page)+'/jornada',wait_until='networkidle')
    message = 'Não foi possível atualizar os marcos' if failed else 'Novos marcos disponíveis'
    expect(page.locator('[data-toast]')).to_contain_text(message)
    live = page.locator('[role="status"]:not([aria-live="off"]), [role="alert"]:not([aria-live="off"])').all_text_contents()
    assert sum(message in content for content in live) == 1


def test_toast_timer_pauses_for_keyboard_focus_and_restores_focus(reading_page):
    from playwright.sync_api import expect
    page = reading_page
    page.clock.install()
    control = page.locator('#q')
    control.focus()
    toast(page, 'Mensagem curta', {'type': 'success', 'duration': 500})
    notice = page.locator('[data-toast]')
    close = notice.get_by_role('button', name='Fechar aviso')
    close.focus()
    page.clock.run_for(7000)
    expect(notice).to_be_visible()
    close.click()
    expect(control).to_be_focused()


def test_notifications_filter_mark_read_and_counter_update(reading_page, app, notices):
    from playwright.sync_api import expect
    page = reading_page
    sign_in(page)
    page.goto(origin(page) + '/social/notifications?state=unread&kind=like')
    expect(page.locator('[data-notification-id]')).to_have_count(1)
    page.locator('[data-notification-id]').get_by_role('button', name='Marcar como lida').click()
    expect(page.locator('[data-notification-id]')).to_have_count(0)
    expect(page.locator('.site-header [data-unread-count]')).to_have_text('2')
    expect(page.locator('[data-notification-empty]')).to_be_visible()
    expect(page.locator('[data-toast]')).to_contain_text('Notificação marcada como lida')


def test_notification_counter_refreshes_without_reloading_or_initial_toast(reading_page, app):
    from criticard.social.service import set_follow
    from playwright.sync_api import expect
    page = reading_page
    sign_in(page)
    page.goto(origin(page)+'/feed', wait_until='networkidle')
    page.locator('[data-toast] button').evaluate_all('nodes => nodes.forEach(node => node.click())')
    with app.app_context():
        set_follow(2, 1, True)
    page.evaluate("window.dispatchEvent(new Event('focus'))")
    expect(page.locator('.site-header [data-unread-count]')).to_have_text('1')
    expect(page.locator('[data-toast]')).to_contain_text('novas notificações')
    assert page.url.endswith('/feed')


def test_reused_sqlite_id_still_announces_a_new_notification(reading_page,app):
    from datetime import timedelta
    from sqlalchemy import delete,insert,select
    from criticard.db import get_db
    from criticard.models import utcnow
    from criticard.social.models import Notification
    from criticard.social.service import set_follow
    from playwright.sync_api import expect
    page = reading_page
    with app.app_context():
        set_follow(2,1,True)
        identity = get_db().execute(select(Notification.id)).scalar()
    sign_in(page)
    page.goto(origin(page)+'/feed',wait_until='networkidle')
    page.locator('[data-toast] button').evaluate_all('nodes => nodes.forEach(node => node.click())')
    with app.app_context():
        with get_db() as db:
            db.execute(delete(Notification).where(Notification.id==identity))
            db.execute(insert(Notification).values(id=identity,recipient_id=1,actor_id=2,
                kind='friend_request',event_key='recreated',created_at=utcnow()+timedelta(seconds=1)))
    page.evaluate("window.dispatchEvent(new Event('focus'))")
    expect(page.locator('[data-toast]')).to_contain_text('novas notificações')
    expect(page.locator('.site-header [data-unread-count]')).to_have_text('1')


def test_native_notifications_and_flashes_work_without_javascript(reading_page, app, notices):
    page = reading_page.context.browser.new_page(java_script_enabled=False, viewport=dict(width=360,height=800))
    try:
        page.goto(origin(reading_page)+'/')
        sign_in(page)
        page.goto(origin(page)+'/social/notifications?state=unread&kind=like')
        assert page.locator('[data-notification-id]').count() == 1
        page.get_by_role('button', name='Ver crítica', exact=True).click()
        page.wait_for_url('**/card/1')
        page.goto(origin(page)+'/social/notifications?state=unread&kind=like')
        assert page.locator('[data-notification-id]').count() == 0
    finally:
        page.close()


def test_backlog_action_uses_shared_toast_feedback(reading_page):
    from playwright.sync_api import expect
    page = reading_page
    sign_in(page)
    page.goto(origin(page)+'/catalogo')
    page.locator('[data-backlog-add]').first.get_by_role('button').click()
    expect(page.locator('[data-toast]')).to_contain_text('Obra adicionada')


def test_connection_action_uses_shared_toast_feedback(reading_page):
    from playwright.sync_api import expect
    page = reading_page
    sign_in(page)
    page.goto(origin(page)+'/perfil/BOB')
    page.locator('[data-connection-form="friendship"]').get_by_role('button', name='Adicionar amigo').click()
    expect(page.locator('[data-toast]')).to_contain_text('Solicitação enviada')


def test_reward_save_uses_shared_toast_feedback(reading_page):
    from playwright.sync_api import expect
    page = reading_page
    sign_in(page)
    page.goto(origin(page)+'/jornada', wait_until='networkidle')
    page.locator('[data-reward-form] button[type=submit]').click()
    expect(page.locator('[data-toast]')).to_contain_text('Personalização salva')


def test_late_search_cannot_restore_a_counter_after_reading(reading_page, app, notices):
    from playwright.sync_api import expect
    page = reading_page
    sign_in(page)
    page.goto(origin(page)+'/criticas', wait_until='networkidle')
    held = []
    def hold(route):
        held.append((route,route.fetch()))
        page.evaluate('window.notificationSearchHeld = true')
    page.route('**/criticas?q=*',hold)
    page.locator('#q').fill('Alice')
    page.wait_for_function('() => window.notificationSearchHeld === true')
    token = page.locator('meta[name=csrf-token]').get_attribute('content')
    response = page.request.post(origin(page)+'/social/notifications/read-all',
        headers={'Accept':'application/json','X-CSRF-Token':token},data={})
    assert response.ok
    page.evaluate("count => document.dispatchEvent(new CustomEvent('criticard:notifications-count',{detail:{count}}))",response.json()['unread_count'])
    held[0][0].fulfill(response=held[0][1])
    expect(page.locator('[data-live-status]')).to_contain_text('resultado')
    expect(page.locator('.site-header [data-unread-count]')).to_have_text('0')


def test_failed_read_preserves_unread_state_and_can_retry(reading_page, notices):
    from playwright.sync_api import expect
    page = reading_page
    sign_in(page)
    page.goto(origin(page)+'/social/notifications?state=unread&kind=like',wait_until='networkidle')
    page.route('**/notifications/1/read',lambda route:route.abort())
    page.get_by_role('button',name='Marcar como lida',exact=True).click()
    expect(page.locator('[data-toast][data-tone=error]')).to_be_visible()
    expect(page.locator('[data-notification-id].is-unread')).to_have_count(1)
    expect(page.locator('.site-header [data-unread-count]')).to_have_text('3')
    page.unroute('**/notifications/1/read')
    page.get_by_role('button',name='Marcar como lida',exact=True).click()
    expect(page.locator('[data-notification-id]')).to_have_count(0)
    expect(page.locator('.site-header [data-unread-count]')).to_have_text('2')


def test_toast_hover_pauses_then_allows_expiration(reading_page):
    from playwright.sync_api import expect
    page = reading_page
    page.emulate_media(reduced_motion='reduce')
    page.clock.install()
    toast(page,'Uma confirmação',{'type':'success','duration':500})
    notice = page.locator('[data-toast]')
    notice.hover()
    page.clock.run_for(7000)
    expect(notice).to_be_visible()
    page.mouse.move(0,0)
    page.clock.run_for(6000)
    expect(notice).to_have_count(0)


def test_block_confirmation_survives_the_required_page_refresh(reading_page):
    from playwright.sync_api import expect
    page = reading_page
    sign_in(page)
    page.goto(origin(page)+'/perfil/BOB')
    page.get_by_role('button',name='Mais opções do perfil de @BOB').click()
    with page.expect_response(lambda response: response.request.method == 'GET' and response.url.endswith('/perfil/BOB')):
        page.locator('[data-block-button]').click()
    page.wait_for_load_state('networkidle')
    expect(page.get_by_role('button',name='Desbloquear',exact=True)).to_be_visible()
    expect(page.locator('[data-toast]')).to_contain_text('Bloqueio atualizado')


def test_action_confirmation_has_one_live_announcement(reading_page):
    from playwright.sync_api import expect
    page = reading_page
    sign_in(page)
    page.goto(origin(page)+'/catalogo')
    page.locator('[data-backlog-add]').first.get_by_role('button').click()
    expect(page.locator('[data-toast-status]')).to_contain_text('Obra adicionada')
    live = page.locator('[role="status"]:not([aria-live="off"])').all_text_contents()
    assert sum('Obra adicionada' in content for content in live) == 1


def test_notification_layout_accessibility_and_visual_evidence(reading_page, app, notices):
    import json
    import tempfile
    from pathlib import Path
    from criticard.config import ROOT
    from criticard.settings.service import save_preferences
    from playwright.sync_api import expect

    with app.app_context():
        save_preferences(1,'aparencia',{'reduce_motion':True,'high_contrast':True,'text_size':'large'})
    page = reading_page
    errors = []
    page.on('pageerror',lambda error:errors.append(str(error)))
    page.on('console',lambda message:errors.append(message.text) if message.type in ('warning','error') else None)
    sign_in(page)
    artifacts = Path(tempfile.mkdtemp(prefix='criticard-notifications-qa-'))
    report = []
    for width,theme in ((360,'graphite'),(768,'graphite'),(1280,'graphite'),(1280,'midnight')):
        with app.app_context():
            save_preferences(1,'aparencia',{'color_scheme':theme})
        page.set_viewport_size(dict(width=width,height=900))
        page.goto(origin(page)+'/social/notifications',wait_until='networkidle')
        expect(page).to_have_title('Notificações · Criti-CARD')
        assert page.locator('[data-notification-id]').count() == 4
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        page.locator('#notification-state').focus()
        expect(page.locator('#notification-state')).to_be_focused()
        toast(page,'Leitura atualizada. Você está em dia.',{'type':'success','duration':0})
        page.screenshot(path=str(artifacts/f'notifications-{width}-{theme}.png'),animations='disabled')
        # Only the synthetic QA page permits axe injection; product CSP stays intact.
        audit = page.context.browser.new_context(bypass_csp=True,viewport=dict(width=width,height=900))
        audit.add_cookies(page.context.cookies())
        audit_page = audit.new_page()
        try:
            audit_page.goto(origin(page)+'/social/notifications',wait_until='networkidle')
            toast(audit_page,'Leitura atualizada. Você está em dia.',{'type':'success','duration':0})
            audit_page.add_script_tag(path=str(ROOT/'node_modules/axe-core/axe.min.js'))
            violations = audit_page.evaluate("async () => (await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa','best-practice']}})).violations.map(item=>({id:item.id,nodes:item.nodes.map(node=>node.target)}))")
            assert not violations,violations
            report.append(dict(width=width,theme=theme,violations=violations))
        finally:
            audit.close()
    assert not errors,errors
    (artifacts/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(f'Notification QA: {artifacts}')
