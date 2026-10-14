from datetime import timedelta

from sqlalchemy import insert, select, update

from criticard.db import get_db
from criticard.models import Card, User, utcnow
from criticard.backlog.models import BacklogItem
from criticard.progression.history import import_user_history
from criticard.progression.models import ProgressionProfile, ExperienceEvent
from criticard.progression.service import record_event


def seed(db):
    for n in range(1,7):
        db.execute(insert(Card).values(author_id=1,obra_id=n,titulo='Old',capa='old.png',sobre='Old',nota=80,archived=1 if n==6 else 0))
    db.execute(insert(BacklogItem).values(user_id=1,work_id=1,status='completed',visibility='private'))


def test_history_outside_cap_once_and_no_invented_weeks(app):
    with app.app_context():
        db = get_db()
        with db:
            seed(db)
            first = import_user_history(db,1,utcnow())
        with db:
            repeated = import_user_history(db,1,utcnow())
        assert first['xp']==215 and first['reviews']==5 and first['completed']==1
        assert repeated['xp']==0
        assert db.execute(select(ExperienceEvent).where(ExperienceEvent.kind=='weekly_activity')).fetchone() is None
        assert db.execute(select(ProgressionProfile.history_imported_at)).scalar() is not None


def test_cli_dry_run_preserves_balance_grants_and_marker(app):
    with app.app_context():
        with get_db() as db:
            seed(db)
    result = app.test_cli_runner().invoke(args=['progression-import-history','--dry-run','--user-id','1'])
    assert result.exit_code==0, result.output
    assert '215' in result.output
    with app.app_context():
        assert get_db().execute(select(ProgressionProfile)).fetchone() is None
        assert get_db().execute(select(ExperienceEvent)).fetchone() is None


def test_import_cannot_replace_consumed_live_origin_and_skips_inactive(app):
    with app.app_context():
        db = get_db()
        now = utcnow()
        with db:
            seed(db)
            for n in range(1,6):
                record_event(db,1,'card_published',f'card:{n}',now,work_id=n,category_id=1)
            capped = record_event(db,1,'work_completed','completed:1',now,work_id=1)
            assert capped.awarded==0
            result = import_user_history(db,1,now)
            db.execute(update(User).where(User.id==2).values(active=0))
            skipped = import_user_history(db,2,now)
        assert result['xp']==0 and skipped['skipped']
        assert db.execute(select(ProgressionProfile).where(ProgressionProfile.user_id==2)).fetchone() is None
