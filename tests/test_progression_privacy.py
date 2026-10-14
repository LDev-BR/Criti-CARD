from conftest import post
from criticard.db import get_db
from criticard.models import utcnow
from criticard.progression.service import record_action
from criticard.progression.queries import public_styles, event_page
from criticard.settings.service import save_preferences


def test_public_optin_exposes_only_limited_summary(app):
    with app.app_context():
        with get_db() as db:
            record_action(db,1,'work_completed',utcnow(),work_id=1,category_id=1)
        hidden = public_styles([1,2])
        assert hidden[1]['public'] is False and 'level' not in hidden[1]
        save_preferences(1,'jornada',{'progression_public':True})
        visible = public_styles([1])[1]
        assert visible['public'] and visible['level']==1
        assert not {'xp','events','work_id','membership_since','user_id'}.intersection(visible)


def test_ledger_is_owner_scoped_and_has_no_review_text(app):
    with app.app_context():
        with get_db() as db:
            record_action(db,1,'card_published',utcnow(),work_id=1,category_id=1)
        assert event_page(2,1)['total']==0
        events = event_page(1,1)
        assert events['total']==2
        assert all('sobre' not in row and 'email' not in row for row in events['items'])
