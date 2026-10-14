"""Read-only private journey and batched, deliberately limited public styles."""
from dataclasses import asdict

from sqlalchemy import func, select

from ..models import User, Work, utcnow
from ..persistence import get_db
from ..settings.models import UserSettings
from ..settings.service import get_preferences, save_preferences
from .access import evaluate_social_access
from .catalog import ACHIEVEMENTS, DAILY_CAP, REWARDS, TIERS, achievement_spec, reward_spec
from .grants import EQUIPMENT_DEFAULTS, eligible_grants, valid_events
from .models import AchievementGrant, ExperienceEvent, ProgressionProfile, RewardGrant
from .policy import as_utc, day_key, level_progress, minimum_xp
from .types import ProgressionError


def _profile(user_id):
    row = get_db().execute(select(ProgressionProfile).where(ProgressionProfile.user_id==user_id)).fetchone()
    return row or dict(user_id=user_id,xp=0,membership_since=None,membership_origin='signup',is_pioneer=0,
        history_imported_at=None,first_contribution_at=None)


def owned_rewards(user_id):
    return {row['slug'] for row in get_db().execute(select(RewardGrant.slug).where(
        RewardGrant.user_id==user_id,RewardGrant.revoked_at.is_(None))).fetchall()} | {
        'title_newcomer','frame_classic','card_classic'}


def reward_inventory(user_id):
    owned = owned_rewards(user_id)
    slugs = set(REWARDS) | owned
    return [dict(spec,owned=slug in owned,requirement=f"Nível {spec['level']}" if 'level' in spec else
        achievement_spec(spec['achievement'])['description']) for slug in sorted(slugs)
        if (spec:=reward_spec(slug))]


def journey_summary(user_id):
    profile = _profile(user_id)
    progress = level_progress(profile['xp'])
    used = get_db().execute(select(func.coalesce(func.sum(ExperienceEvent.delta),0)).where(
        ExperienceEvent.user_id==user_id,ExperienceEvent.quota_day==day_key(utcnow()),
        ExperienceEvent.origin=='live',ExperienceEvent.delta>0)).scalar()
    next_tier = next((dict(tier,xp=minimum_xp(tier['level'])) for tier in TIERS if tier['level']>progress.level),None)
    next_badge = next((n for n in range(5,101,5) if n>progress.level),None)
    social_unlock_specs = (
        ('join_open_chat','Entrar em chats abertos',0),
        ('create_group_chat','Criar grupos e entrar nos fechados',3),
        ('create_community','Criar uma comunidade',0),
    )
    social_unlocks = []
    for action,label,required_cap_days in social_unlock_specs:
        decision = evaluate_social_access(get_db(),user_id,action,utcnow())
        social_unlocks.append(dict(action=action,label=label,required_cap_days=required_cap_days,
            remaining_xp=max(0,decision.required_xp-decision.current_xp),
            remaining_level=max(0,decision.required_level-decision.current_level),
            **decision.as_dict()))
    return dict(**asdict(progress),percent=round(progress.xp_into_level/(progress.xp_into_level+progress.xp_to_next_level)*100),
        daily_remaining=max(0,DAILY_CAP-used),daily_cap=DAILY_CAP,next_tier=next_tier,next_badge=next_badge,
        social_unlocks=social_unlocks,
        membership_since=profile['membership_since'],membership_origin=profile['membership_origin'],
        pioneer=bool(profile['is_pioneer']),history_imported_at=profile['history_imported_at'])


def event_page(user_id,page):
    if type(page) is not int or not 1<=page<=1_000_000:
        raise ProgressionError('Página não encontrada.',404)
    db = get_db()
    total = db.execute(select(func.count()).select_from(ExperienceEvent).where(ExperienceEvent.user_id==user_id)).scalar()
    pages = max(1,(total+19)//20)
    if page>pages:
        raise ProgressionError('Página não encontrada.',404)
    items = db.execute(select(ExperienceEvent,Work.titulo.label('work_title')).outerjoin(Work,Work.id==ExperienceEvent.work_id)
        .where(ExperienceEvent.user_id==user_id).order_by(ExperienceEvent.id.desc()).limit(20).offset((page-1)*20)).fetchall()
    for item in items:
        item['created_at'] = as_utc(item['created_at'])
    return dict(items=items,total=total,page=page,pages=pages)


def achievement_list(user_id,state):
    if state not in ('all','unlocked','progress'):
        raise ProgressionError('Filtro de conquistas inválido.',404)
    profile = _profile(user_id)
    _,_,counts = eligible_grants(profile,valid_events(get_db(),user_id))
    grants = {row['slug']:row for row in get_db().execute(select(AchievementGrant).where(AchievementGrant.user_id==user_id)).fetchall()}
    days = max(0,(utcnow()-as_utc(profile['membership_since'])).days) if profile['membership_since'] else 0
    slugs = (*ACHIEVEMENTS,*(f'level_{n:03}' for n in range(5,101,5)),
        *sorted({'anniversary_1',*(slug for slug in grants if slug.startswith('anniversary_'))}))
    items = []
    for slug in slugs:
        spec = achievement_spec(slug)
        row = grants.get(slug)
        unlocked = bool(row and row['revoked_at'] is None)
        count = level_progress(profile['xp']).level if slug.startswith('level_') else (
            days if slug.startswith(('tenure_','anniversary_')) else counts.get(slug,0))
        if state=='all' or (unlocked if state=='unlocked' else not unlocked):
            items.append(dict(spec,unlocked=unlocked,current=min(spec['target'],count),
                percent=min(100,round(count/spec['target']*100)),granted_at=row['granted_at'] if unlocked else None))
    return items


def _style(preferences,owned,profile,public):
    choices = {}
    for field,default in EQUIPMENT_DEFAULTS.items():
        value = preferences.get(field,default)
        choices[field] = value if isinstance(value,str) and value in owned and reward_spec(value) else default
    style = dict(public=public,title_slug=choices['progression_title'],
        title_name=reward_spec(choices['progression_title'])['name'],frame_slug=choices['progression_frame'],
        card_slug=choices['progression_card'],badge_slug=choices['progression_badge'],
        badge_name=reward_spec(choices['progression_badge'])['name'] if choices['progression_badge'] else '')
    if public:
        progress = level_progress(profile['xp'])
        style.update(level=progress.level,tier_slug=progress.tier_slug,tier_name=progress.tier_name)
    return style


def public_styles(user_ids):
    ids = list(set(user_ids))
    if not ids:
        return {}
    rows = get_db().execute(select(ProgressionProfile,UserSettings.preferences).join(User,User.id==ProgressionProfile.user_id)
        .outerjoin(UserSettings,UserSettings.user_id==ProgressionProfile.user_id)
        .where(ProgressionProfile.user_id.in_(ids),User.active==1)).fetchall()
    grants = get_db().execute(select(RewardGrant.user_id,RewardGrant.slug).where(RewardGrant.user_id.in_(ids),
        RewardGrant.revoked_at.is_(None))).fetchall()
    owned = {uid:{'title_newcomer','frame_classic','card_classic'} for uid in ids}
    for row in grants:
        owned[row['user_id']].add(row['slug'])
    plain = _style({},set(EQUIPMENT_DEFAULTS.values()),{'xp':0},False)
    result = {uid:dict(plain) for uid in ids}
    for row in rows:
        preferences = row['preferences'] or {}
        if preferences.get('progression_public') is True:
            result[row['user_id']] = _style(preferences,owned[row['user_id']],row,True)
    return result


def equipment_style(user_id):
    return _style(get_preferences(user_id),owned_rewards(user_id),_profile(user_id),True)


def save_equipment(user_id,choices):
    return save_preferences(user_id,'jornada',choices)
