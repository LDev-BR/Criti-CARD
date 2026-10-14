import pytest
from sqlalchemy import delete, func, select

from conftest import post
from criticard.db import get_db
from criticard.models import User, utcnow
from criticard.progression.models import AchievementGrant, ExperienceEvent, ProgressionProfile, RewardGrant
from criticard.progression.service import record_action, record_event, revoke_event
from criticard.progression.types import ProgressionError
from criticard.settings.service import get_preferences, save_preferences


def test_correction_once_revokes_equipment_and_legitimate_gain_restores(app):
    with app.app_context():
        db = get_db()
        with db:
            now = utcnow()
            # Prior imported XP puts the account just below the Apprentice reward;
            # live reviews cross the threshold before one of them is corrected.
            for work_id in range(1,20):
                record_event(db,1,'card_published',f'card:{work_id}',now,
                    work_id=work_id,category_id=1,origin='history')
            for work_id in range(1,15):
                record_event(db,1,'work_completed',f'completed:{work_id}',now,
                    work_id=work_id,category_id=1,origin='history')
            awards = [record_action(db,1,'card_published',now,work_id=n,category_id=1)
                for n in (20,21,22)]
        save_preferences(1,'chat',{'chat_enter_send':False})
        save_preferences(1,'jornada',{'progression_frame':'frame_slate','progression_card':'card_slate'})
        with db:
            result = revoke_event(db,3,awards[0].event_id,'Abuso confirmado após revisão.',utcnow())
            repeated = revoke_event(db,3,awards[0].event_id,'Repetição da mesma correção.',utcnow())
        assert result.total_xp==1060 and result.awarded==-40 and repeated.awarded==0
        assert db.execute(select(func.count()).select_from(ExperienceEvent).where(ExperienceEvent.kind=='reversal')).scalar()==1
        preferences = get_preferences(1)
        assert preferences['progression_frame']=='frame_classic'
        assert preferences['progression_card']=='card_classic'
        assert preferences['chat_enter_send'] is False
        with db:
            record_action(db,1,'card_published',utcnow(),work_id=23,category_id=1)
        grant = db.execute(select(RewardGrant).where(RewardGrant.user_id==1,RewardGrant.slug=='frame_slate')).fetchone()
        assert grant['revoked_at'] is None
        with db:
            db.execute(delete(User).where(User.id==3))
        reversal = db.execute(select(ExperienceEvent).where(ExperienceEvent.kind=='reversal')).fetchone()
        assert reversal['actor_id'] is None and reversal['reason']=='Abuso confirmado após revisão.'


def test_zero_xp_correction_invalidates_fact_without_refunding_cap(app):
    with app.app_context():
        db = get_db()
        with db:
            for n in range(1,15):
                record_event(db,1,'work_completed',f'completed:{n}',utcnow(),work_id=n)
            zero = record_action(db,1,'card_published',utcnow(),work_id=20,category_id=1)
            assert zero.awarded==0
            assert db.execute(select(AchievementGrant).where(AchievementGrant.slug=='first_review')).fetchone()
            revoke_event(db,3,zero.event_id,'Crítica abusiva confirmada.',utcnow())
        grant = db.execute(select(AchievementGrant).where(AchievementGrant.slug=='first_review')).fetchone()
        assert grant['revoked_at'] is not None
        assert db.execute(select(ProgressionProfile.xp).where(ProgressionProfile.user_id==1)).scalar()==200


def test_admin_routes_reject_users_and_escape_reason(client,app):
    post(client,'/',{'username':'alice','senha':'Password1!'})
    assert client.get('/admin/jornada/2').status_code==403
    with app.app_context():
        with get_db() as db:
            award = record_action(db,1,'card_published',utcnow(),work_id=1,category_id=1)
    assert post(client,f'/admin/jornada/eventos/{award.event_id}/revogar',{'reason':'Abuso confirmado.'}).status_code==403
    post(client,'/',{'username':'admin','senha':'Password1!'})
    assert client.post(f'/admin/jornada/eventos/{award.event_id}/revogar',data={'reason':'Abuso confirmado.'}).status_code==400
    assert post(client,f'/admin/jornada/eventos/{award.event_id}/revogar',{'reason':'<script>alert(1)</script>'}).status_code==302
    page = client.get('/admin/jornada/1').text
    assert '&lt;script&gt;' in page and '<script>alert(1)</script>' not in page


@pytest.mark.parametrize('identity,reason',[(True,'Abuso confirmado.'),(2**70,'Abuso confirmado.'),(1,'curto'),(1,{}),(1,'x'*501)])
def test_invalid_correction_is_rejected(app,identity,reason):
    with app.app_context():
        with pytest.raises(ProgressionError):
            with get_db() as db:
                revoke_event(db,3,identity,reason,utcnow())
