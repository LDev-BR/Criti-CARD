"""Reconcile earned cosmetics from the valid ledger, inside the owner's lock."""
from sqlalchemy import insert, select, update

from ..settings.models import UserSettings
from .catalog import TIERS
from .models import AchievementGrant, ExperienceEvent, ProgressionProfile, RewardGrant
from .policy import level_progress
from .types import GrantChanges

EQUIPMENT_DEFAULTS = dict(progression_title='title_newcomer',progression_frame='frame_classic',
    progression_card='card_classic',progression_badge='')


def valid_events(db,user_id):
    reversed_ids = select(ExperienceEvent.reverses_event_id).where(
        ExperienceEvent.user_id==user_id,ExperienceEvent.reverses_event_id.is_not(None))
    return db.execute(select(ExperienceEvent).where(ExperienceEvent.user_id==user_id,
        ExperienceEvent.reverses_event_id.is_(None),ExperienceEvent.id.not_in(reversed_ids))).fetchall()


def eligible_grants(profile,events):
    level = level_progress(profile['xp']).level
    reviews = [event for event in events if event['kind']=='card_published']
    completed = sum(event['kind']=='work_completed' for event in events)
    weeks = sum(event['kind']=='weekly_activity' for event in events)
    categories = {event['category_id'] for event in reviews if event['category_id'] is not None}
    keys = {event['event_key'] for event in events}
    counts = dict(first_review=len(reviews),reviews_5=len(reviews),reviews_10=len(reviews),
        categories_3=len(categories),completed_5=completed,weeks_4=weeks,pioneer=profile['is_pioneer'])
    achievements = {slug for slug,target in (('first_review',1),('reviews_5',5),('reviews_10',10),
        ('categories_3',3),('completed_5',5),('weeks_4',4),('pioneer',1)) if counts[slug]>=target}
    achievements.update(f'level_{n:03}' for n in range(5,min(level,100)+1,5))
    achievements.update(f'tenure_{n}' for n in (30,90,180) if f'tenure:{n}' in keys)
    achievements.update(key.replace(':','_') for key in keys if key.startswith('anniversary:'))
    rewards = {'badge_'+slug for slug in achievements}
    for tier in TIERS:
        if level >= tier['level']:
            rewards.update(('title_'+tier['slug'],'frame_'+tier['material'],'card_'+tier['material']))
    if 'tenure_90' in achievements:
        rewards.add('frame_aurora')
    if 'anniversary_1' in achievements:
        rewards.add('frame_heritage')
    return achievements, rewards, counts


def _reconcile(db,model,user_id,eligible,now,*,preserve_legacy=True):
    existing = {row['slug']:row for row in db.execute(select(model).where(model.user_id==user_id)).fetchall()}
    added, revoked = [], []
    for slug in sorted(eligible):
        row = existing.get(slug)
        if row is None:
            db.execute(insert(model).values(user_id=user_id,slug=slug,granted_at=now))
            added.append(slug)
        elif row['revoked_at'] is not None:
            db.execute(update(model).where(model.user_id==user_id,model.slug==slug)
                .values(granted_at=now,revoked_at=None,notice_seen_at=None))
            added.append(slug)
    for slug,row in existing.items():
        if slug not in eligible and row['revoked_at'] is None and not (
                preserve_legacy and row['legacy_protected']):
            db.execute(update(model).where(model.user_id==user_id,model.slug==slug).values(revoked_at=now))
            revoked.append(slug)
    return tuple(added),tuple(revoked)


def reconcile_grants(db,user_id,now,*,preserve_legacy=True):
    profile = db.execute(select(ProgressionProfile).where(ProgressionProfile.user_id==user_id)).fetchone()
    achievements,rewards,_ = eligible_grants(profile,valid_events(db,user_id))
    added_a,revoked_a = _reconcile(db,AchievementGrant,user_id,achievements,now,
        preserve_legacy=preserve_legacy)
    added_r,revoked_r = _reconcile(db,RewardGrant,user_id,rewards,now,
        preserve_legacy=preserve_legacy)
    stored = db.execute(select(UserSettings.preferences).where(UserSettings.user_id==user_id)).scalar()
    if stored:
        preferences = dict(stored)
        for field,default in EQUIPMENT_DEFAULTS.items():
            if preferences.get(field) and preferences[field] not in rewards:
                preferences[field] = default
        if preferences != stored:
            db.execute(update(UserSettings).where(UserSettings.user_id==user_id).values(preferences=preferences,updated_at=now))
    return GrantChanges(added_a,added_r,revoked_a,revoked_r)
