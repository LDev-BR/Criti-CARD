"""Progression mutations never commit: the action's transaction owns durability."""
from sqlalchemy import func, insert, select, update

from ..models import User
from ..settings.service import get_preferences
from .catalog import DAILY_CAP, RULE_VERSION
from .grants import reconcile_grants
from .models import AchievementGrant, ExperienceEvent, ProgressionProfile, RewardGrant
from .policy import as_utc, day_key, level_progress, tenure_milestones, week_key
from .types import Notice, ProgressionError, XpAward


def lock_owner(db,user_id):
    if type(user_id) is not int or not 1<=user_id<=2**63-1:
        raise ProgressionError('Conta não encontrada.',404)
    if db.dialect=='sqlite':
        owner = db.execute(update(User).where(User.id==user_id).values(session_version=User.session_version)
            .returning(*User.__table__.columns)).fetchone()
    else:
        owner = db.execute(select(User).where(User.id==user_id).with_for_update()).fetchone()
    if owner is None:
        raise ProgressionError('Conta não encontrada.',404)
    if not owner['active']:
        raise ProgressionError('Esta conta está desativada.',403)
    return owner


def require_owner_session(owner):
    """Recheck an HTTP actor after locking; internal/CLI calls stay independent."""
    from flask import g, has_request_context, session
    from ..security import valid_session_identity

    if has_request_context() and (not getattr(g,'user',None) or
            g.user['id'] != owner['id'] or not valid_session_identity(owner,session)):
        session.clear()
        g.user = None
        raise ProgressionError('Sua sessão expirou. Entre novamente.',401)


def ensure_profile(db,user_id,now):
    owner = lock_owner(db,user_id)
    profile = db.execute(select(ProgressionProfile).where(ProgressionProfile.user_id==user_id)).fetchone()
    if profile is None:
        db.execute(insert(ProgressionProfile).values(user_id=user_id,
            membership_since=as_utc(owner['created_at'] or now),
            membership_origin='signup' if owner['created_at'] else 'rollout'))
        profile = db.execute(select(ProgressionProfile).where(ProgressionProfile.user_id==user_id)).fetchone()
    return profile


def _award(event_id,delta,before,after):
    return XpAward(event_id,delta,after,level_progress(before).level,level_progress(after).level)


def record_event(db,user_id,kind,source_key,now,*,work_id=None,category_id=None,origin='live',milestone=None):
    profile = ensure_profile(db,user_id,now)
    if origin not in ('live','history','tenure'):
        raise ProgressionError('Origem de experiência inválida.')
    if kind in ('card_published','work_completed'):
        if type(work_id) is not int or not 1<=work_id<=2**63-1:
            raise ProgressionError('Obra inválida.')
        expected = ('card:' if kind=='card_published' else 'completed:')+str(work_id)
        base = 40 if kind=='card_published' else 15
    elif kind=='weekly_activity' and origin=='live':
        expected,base = 'week:'+week_key(now),10
    elif kind=='tenure' and origin=='tenure':
        milestones = dict(tenure_milestones(profile['membership_since'],now))
        if milestone not in milestones:
            raise ProgressionError('Marco de permanência inválido.')
        expected,base = milestone,milestones[milestone]
    else:
        raise ProgressionError('Evento de experiência inválido.')
    if source_key != expected:
        raise ProgressionError('Origem de experiência inválida.')
    existing = db.execute(select(ExperienceEvent.id).where(ExperienceEvent.user_id==user_id,
        ExperienceEvent.event_key==source_key)).scalar()
    if existing is not None:
        return _award(None,0,profile['xp'],profile['xp'])
    now = as_utc(now)
    delta = base
    if origin=='live':
        used = db.execute(select(func.coalesce(func.sum(ExperienceEvent.delta),0)).where(
            ExperienceEvent.user_id==user_id,ExperienceEvent.quota_day==day_key(now),
            ExperienceEvent.origin=='live',ExperienceEvent.delta>0)).scalar()
        delta = min(base,max(0,DAILY_CAP-used))
    reason = 'Cota diária esgotada; esta origem não gera crédito para outro dia.' if delta==0 else (
        'Ganho parcial devido à cota diária.' if delta<base else None)
    event_id = db.execute(insert(ExperienceEvent).values(user_id=user_id,event_key=source_key,kind=kind,
        origin=origin,delta=delta,work_id=work_id,category_id=category_id,created_at=now,quota_day=day_key(now),
        rule_version=RULE_VERSION,reason=reason).returning(ExperienceEvent.id)).scalar()
    after = profile['xp']+delta
    db.execute(update(ProgressionProfile).where(ProgressionProfile.user_id==user_id).values(xp=after))
    return _award(event_id,delta,profile['xp'],after)


def _sync_age(db,user_id,now):
    profile = ensure_profile(db,user_id,now)
    for key,_ in tenure_milestones(profile['membership_since'],now):
        record_event(db,user_id,'tenure',key,now,origin='tenure',milestone=key)


def sync_user(db,user_id,now):
    before = ensure_profile(db,user_id,now)['xp']
    _sync_age(db,user_id,now)
    reconcile_grants(db,user_id,now)
    after = ensure_profile(db,user_id,now)['xp']
    return _award(None,after-before,before,after)


def record_action(db,user_id,kind,now,*,work_id=None,category_id=None):
    if kind not in ('card_published','work_completed','activity'):
        raise ProgressionError('Ação de participação inválida.')
    profile = ensure_profile(db,user_id,now)
    before = profile['xp']
    if profile['first_contribution_at'] is None:
        db.execute(update(ProgressionProfile).where(ProgressionProfile.user_id==user_id,
            ProgressionProfile.first_contribution_at.is_(None)).values(first_contribution_at=as_utc(now)))
    _sync_age(db,user_id,now)
    primary = None
    if kind != 'activity':
        key = ('card:' if kind=='card_published' else 'completed:')+str(work_id)
        primary = record_event(db,user_id,kind,key,now,work_id=work_id,category_id=category_id)
    weekly = record_event(db,user_id,'weekly_activity','week:'+week_key(now),now)
    reconcile_grants(db,user_id,now)
    after = ensure_profile(db,user_id,now)['xp']
    return _award(primary.event_id if primary else weekly.event_id,after-before,before,after)


def claim_notice(db,user_id,now):
    profile = ensure_profile(db,user_id,now)
    slugs = []
    for model in (AchievementGrant,RewardGrant):
        pending = tuple(row['slug'] for row in db.execute(select(model.slug).where(model.user_id==user_id,
            model.revoked_at.is_(None),model.notice_seen_at.is_(None))).fetchall())
        db.execute(update(model).where(model.user_id==user_id,model.notice_seen_at.is_(None)).values(notice_seen_at=now))
        slugs.append(pending)
    level = level_progress(profile['xp']).level
    db.execute(update(ProgressionProfile).where(ProgressionProfile.user_id==user_id).values(notice_level=level))
    # Consume muted notices too: turning them back on must not produce a backlog.
    if not get_preferences(user_id).get('progression_notices',True) or not (slugs[0] or slugs[1] or level>profile['notice_level']):
        return None
    return Notice(profile['notice_level'],level,*slugs)


def revoke_event(db,admin_id,event_id,reason,now):
    from flask import g, has_request_context, session
    from ..security import valid_session_identity
    from ..validation import storable_text
    if type(admin_id) is not int or type(event_id) is not int or not 1<=event_id<=2**63-1 or not 1<=admin_id<=2**63-1:
        raise ProgressionError('Evento não encontrado.',404)
    if not storable_text(reason) or not 10<=len(reason.strip())<=500:
        raise ProgressionError('Explique a correção em 10 a 500 caracteres.',field='reason')
    probe = db.execute(select(ExperienceEvent.user_id).where(ExperienceEvent.id==event_id)).scalar()
    if probe is None:
        raise ProgressionError('Evento não encontrado.',404)
    ids = sorted({admin_id,probe})
    if db.dialect=='sqlite':
        locked = db.execute(update(User).where(User.id.in_(ids)).values(session_version=User.session_version)
            .returning(*User.__table__.columns)).fetchall()
    else:
        locked = db.execute(select(User).where(User.id.in_(ids)).order_by(User.id).with_for_update()).fetchall()
    users = {row['id']:row for row in locked}
    administrator = users.get(admin_id)
    if not administrator or not administrator['active'] or administrator['admin']!=1:
        raise ProgressionError('Acesso administrativo necessário.',403)
    if has_request_context() and (not g.user or g.user['id']!=admin_id or not valid_session_identity(administrator,session)):
        raise ProgressionError('Sua sessão expirou. Entre novamente.',401)
    event = db.execute(select(ExperienceEvent).where(ExperienceEvent.id==event_id)).fetchone()
    if event is None or probe not in users:
        raise ProgressionError('Evento não encontrado.',404)
    if event['kind']=='reversal' or event['reverses_event_id'] is not None:
        raise ProgressionError('Uma correção não pode corrigir outra correção.')
    profile = db.execute(select(ProgressionProfile).where(ProgressionProfile.user_id==probe)).fetchone()
    existing = db.execute(select(ExperienceEvent.id).where(ExperienceEvent.reverses_event_id==event_id)).scalar()
    if existing is not None:
        return _award(None,0,profile['xp'],profile['xp'])
    after = profile['xp']-event['delta']
    if after<0:
        raise ProgressionError('Saldo inconsistente. Revise o histórico antes de corrigir.',409)
    correction = db.execute(insert(ExperienceEvent).values(user_id=probe,event_key=f'reversal:{event_id}',
        kind='reversal',origin='admin',delta=-event['delta'],created_at=as_utc(now),quota_day=day_key(now),
        rule_version=RULE_VERSION,reason=reason.strip(),actor_id=admin_id,reverses_event_id=event_id)
        .returning(ExperienceEvent.id)).scalar()
    db.execute(update(ProgressionProfile).where(ProgressionProfile.user_id==probe).values(xp=after))
    reversed_ids = select(ExperienceEvent.reverses_event_id).where(
        ExperienceEvent.user_id==probe,ExperienceEvent.reverses_event_id.is_not(None))
    first_contribution = db.execute(select(func.min(ExperienceEvent.created_at)).where(
        ExperienceEvent.user_id==probe,ExperienceEvent.origin=='live',
        ExperienceEvent.kind.in_(('card_published','work_completed','weekly_activity')),
        ExperienceEvent.id.not_in(reversed_ids))).scalar()
    db.execute(update(ProgressionProfile).where(ProgressionProfile.user_id==probe)
        .values(first_contribution_at=first_contribution))
    reconcile_grants(db,probe,now,preserve_legacy=False)
    return _award(correction,-event['delta'],profile['xp'],after)
