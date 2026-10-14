from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, insert, select, text

from test_postgres import pg_app, pg_database_url, in_app
from criticard.db import delete_user, get_db
from criticard.models import Card, utcnow
from criticard.progression.history import import_user_history
from criticard.progression.models import ExperienceEvent, ProgressionProfile
from criticard.progression.service import record_action, revoke_event
from criticard.progression.types import ProgressionError
from criticard.settings.service import SettingsError, get_preferences, save_preferences


def award(app,user_id,work_id):
    def action():
        with get_db() as db:
            return record_action(db,user_id,'card_published',utcnow(),work_id=work_id,category_id=1)
    return in_app(app,action)


def test_parallel_origin_and_quota_are_serialized_per_owner(pg_app):
    with ThreadPoolExecutor(max_workers=8) as pool:
        same = list(pool.map(lambda _:award(pg_app,1,1),range(8)))
        more = list(pool.map(lambda n:award(pg_app,1,n),range(2,10)))
        bob = pool.submit(award,pg_app,2,1).result()
    assert sum(result.awarded for result in same)==50
    assert sum(result.awarded for result in more)==150
    assert bob.total_xp==50
    with pg_app.app_context():
        db = get_db()
        assert db.execute(select(func.count()).select_from(ExperienceEvent).where(
            ExperienceEvent.user_id==1,ExperienceEvent.event_key=='card:1')).scalar()==1
        assert db.execute(select(ProgressionProfile.xp).where(ProgressionProfile.user_id==1)).scalar()==200
        assert db.execute(select(func.sum(ExperienceEvent.delta)).where(ExperienceEvent.user_id==1)).scalar()==200


def test_equipping_during_revocation_preserves_eligible_state(pg_app):
    first = award(pg_app,1,1)
    award(pg_app,1,2)
    award(pg_app,1,3)
    with pg_app.app_context():
        save_preferences(1,'chat',{'chat_enter_send':False})
    def equip():
        try:
            return in_app(pg_app,lambda:save_preferences(1,'jornada',{'progression_frame':'frame_slate'}))
        except SettingsError:
            return None
    def revoke():
        with pg_app.app_context():
            with get_db() as db:
                return revoke_event(db,3,first.event_id,'Abuso confirmado na revisão.',utcnow())
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(equip),pool.submit(revoke)]
        for future in futures:
            future.result(timeout=15)
    with pg_app.app_context():
        prefs = get_preferences(1)
        assert prefs['progression_frame']=='frame_classic'
        assert prefs['chat_enter_send'] is False


def test_import_and_publication_same_work_award_once(pg_app):
    with pg_app.app_context():
        with get_db() as db:
            db.execute(insert(Card).values(author_id=1,obra_id=1,titulo='Work',capa='test.png',sobre='Review',nota=90))
    def historical():
        with pg_app.app_context():
            with get_db() as db:
                return import_user_history(db,1,utcnow())
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(historical),pool.submit(award,pg_app,1,1)]
        for future in futures:
            future.result(timeout=15)
    with pg_app.app_context():
        assert get_db().execute(select(ProgressionProfile.xp).where(ProgressionProfile.user_id==1)).scalar()==50
        assert get_db().execute(select(func.count()).select_from(ExperienceEvent).where(
            ExperienceEvent.event_key=='card:1')).scalar()==1


def test_deleting_during_award_leaves_no_orphans(pg_app):
    def gain():
        try:
            return award(pg_app,1,1)
        except ProgressionError as error:
            assert error.status==404
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(gain),pool.submit(in_app,pg_app,lambda:delete_user(1))]
        for future in futures:
            future.result(timeout=15)
    with pg_app.app_context():
        assert get_db().execute(select(ExperienceEvent).where(ExperienceEvent.user_id==1)).fetchone() is None
        assert get_db().execute(select(ProgressionProfile).where(ProgressionProfile.user_id==1)).fetchone() is None


@pytest.mark.parametrize('template', ['progression/events.html', 'admin/progression.html'])
def test_ledger_displays_utc_when_postgres_session_uses_local_timezone(pg_app, template):
    from flask import g, render_template
    from criticard.progression.queries import event_page, journey_summary

    with pg_app.test_request_context():
        g.user = None
        with get_db() as db:
            record_action(db, 1, 'card_published',
                datetime(2026, 10, 11, 12, tzinfo=timezone.utc), work_id=1, category_id=1)
        get_db().execute(text("SET TIME ZONE 'America/Sao_Paulo'"))
        html = render_template(template,
            events=event_page(1, 1), achievement_state='all', reversed_ids=set(),
            owner=dict(id=1, username='ALICE'), summary=journey_summary(1),
            usuario_atual=None, csrf_token=lambda: 'test-csrf')
        assert '11/10/2026 12:00 UTC' in html
        assert '11/10/2026 09:00 UTC' not in html
