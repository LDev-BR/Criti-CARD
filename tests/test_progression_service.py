from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, update

from criticard.db import get_db
from criticard.models import User
from criticard.progression.models import ProgressionProfile, ExperienceEvent, RewardGrant
from criticard.progression.service import record_event, record_action, sync_user, claim_notice, ensure_profile
from criticard.progression.types import ProgressionError

NOW = datetime(2026,10,11,12,tzinfo=timezone.utc)


def test_per_work_keys_are_permanent_and_owner_scoped(app):
    with app.app_context():
        db = get_db()
        with db:
            first = record_event(db,1,'card_published','card:1',NOW,work_id=1,category_id=1)
            repeated = record_event(db,1,'card_published','card:1',NOW+timedelta(days=1),work_id=1,category_id=1)
            bob = record_event(db,2,'card_published','card:1',NOW,work_id=1,category_id=1)
        assert first.awarded == 40 and first.level_after == 1
        assert repeated.awarded == 0 and repeated.total_xp == 40
        assert bob.awarded == 40
        assert db.execute(select(ProgressionProfile.is_pioneer).where(ProgressionProfile.user_id==1)).scalar() == 0


def test_daily_cap_partial_zero_and_no_deferred_credit(app):
    with app.app_context():
        db = get_db()
        with db:
            for n in range(1,4):
                record_event(db,1,'card_published',f'card:{n}',NOW,work_id=n,category_id=1)
            for n in range(4,9):
                record_event(db,1,'work_completed',f'completed:{n}',NOW,work_id=n,category_id=1)
            partial = record_event(db,1,'card_published','card:9',NOW,work_id=9,category_id=1)
            capped = record_event(db,1,'card_published','card:10',NOW,work_id=10,category_id=1)
            retry = record_event(db,1,'card_published','card:10',NOW+timedelta(days=1),work_id=10,category_id=1)
        assert partial.awarded == 5
        assert capped.awarded == retry.awarded == 0
        assert retry.total_xp == 200
        assert db.execute(select(ExperienceEvent.reason).where(ExperienceEvent.id==capped.event_id)).scalar()


def test_external_rollback_removes_awards_grants_and_notice(app):
    with app.app_context():
        db = get_db()
        with pytest.raises(RuntimeError):
            with db:
                record_action(db,1,'card_published',NOW,work_id=1,category_id=1)
                notice = claim_notice(db,1,NOW)
                assert notice.level_after == 1
                assert 'first_review' in notice.achievement_slugs
                raise RuntimeError('action failed')
        assert db.execute(select(ProgressionProfile)).fetchone() is None
        assert db.execute(select(ExperienceEvent)).fetchone() is None
        assert db.execute(select(RewardGrant)).fetchone() is None


def test_age_and_week_are_idempotent_and_notice_aggregated(app):
    with app.app_context():
        db = get_db()
        with db:
            db.execute(update(User).where(User.id==1).values(created_at=NOW-timedelta(days=730)))
            award = record_action(db,1,'card_published',NOW,work_id=1,category_id=1)
            notice = claim_notice(db,1,NOW)
            repeated = sync_user(db,1,NOW)
            assert claim_notice(db,1,NOW) is None
        assert award.total_xp == 1100  # 50+100+150+250+500 +40+10
        assert repeated.awarded == 0
        assert notice.level_after == 11
        assert len(notice.achievement_slugs)>5


def test_inactive_and_unknown_kinds_cannot_award(app):
    with app.app_context():
        db = get_db()
        with db:
            db.execute(update(User).where(User.id==1).values(active=0))
        with pytest.raises(ProgressionError):
            with db:
                sync_user(db,1,NOW)
        with pytest.raises(ProgressionError):
            with db:
                record_action(db,2,'like',NOW)
        assert db.execute(select(ExperienceEvent)).fetchone() is None
