"""Explicit, resumable per-owner backfill; no invented historic activity."""
from sqlalchemy import select, update

from ..backlog.models import BacklogItem
from ..models import Card, Work
from .models import ProgressionProfile
from .service import ensure_profile, record_event, sync_user
from .types import ProgressionError


def import_user_history(db,user_id,now):
    result = dict(user_id=user_id,reviews=0,completed=0,xp=0,skipped=False)
    try:
        profile = ensure_profile(db,user_id,now)
    except ProgressionError as error:
        if error.status==403:
            return {**result,'skipped':True}
        raise
    if profile['history_imported_at'] is not None:
        return result
    reviews = db.execute(select(Card.obra_id,Work.categoria_id).join(Work,Work.id==Card.obra_id)
        .where(Card.author_id==user_id,Card.archived==0).distinct()).fetchall()
    completed = db.execute(select(BacklogItem.work_id,Work.categoria_id).join(Work,Work.id==BacklogItem.work_id)
        .where(BacklogItem.user_id==user_id,BacklogItem.status=='completed')).fetchall()
    for kind,rows,prefix,count_name in (('card_published',reviews,'card','reviews'),
        ('work_completed',completed,'completed','completed')):
        for row in rows:
            award = record_event(db,user_id,kind,f'{prefix}:{row[0]}',now,
                work_id=row[0],category_id=row[1],origin='history')
            result[count_name] += award.event_id is not None
    sync_user(db,user_id,now)
    result['xp'] = ensure_profile(db,user_id,now)['xp']-profile['xp']
    db.execute(update(ProgressionProfile).where(ProgressionProfile.user_id==user_id).values(history_imported_at=now))
    return result
