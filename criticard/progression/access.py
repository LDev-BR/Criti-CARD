"""Server-side social eligibility from XP, elapsed time and quota history."""
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select

from .catalog import DAILY_CAP
from .models import ExperienceEvent, ProgressionProfile
from .policy import as_utc, level_progress, minimum_xp


@dataclass(frozen=True)
class AccessDecision:
    eligible: bool
    reason: str | None
    current_xp: int
    required_xp: int
    current_level: int
    required_level: int
    first_contribution_at: datetime | None
    full_cap_days: int
    hours_remaining: float

    def as_dict(self):
        return asdict(self)


_GATES = {
    'join_open_chat': (3, 24, 0, True),
    'join_closed_chat': (6, 48, 3, True),
    'create_group_chat': (6, 48, 3, True),
    'create_community': (1, 168, 0, True),
    'join_open_community': (1, 0, 0, False),
    'join_closed_community': (1, 0, 0, False),
}


def _full_cap_days(db, user_id):
    reversed_ids = select(ExperienceEvent.reverses_event_id).where(
        ExperienceEvent.user_id == user_id,
        ExperienceEvent.reverses_event_id.is_not(None))
    days = db.execute(select(ExperienceEvent.quota_day).where(
        ExperienceEvent.user_id == user_id,
        ExperienceEvent.origin == 'live',
        ExperienceEvent.delta > 0,
        ExperienceEvent.id.not_in(reversed_ids)
    ).group_by(ExperienceEvent.quota_day).having(
        func.sum(ExperienceEvent.delta) == DAILY_CAP)).fetchall()
    return len(days)


def evaluate_social_access(db, user_id: int, action: str, now, *, minimum_level: int = 1) -> AccessDecision:
    if action not in _GATES:
        raise ValueError('Ação social inválida.')
    if type(minimum_level) is not int or minimum_level < 1:
        raise ValueError('O nível mínimo deve ser um inteiro positivo.')

    required_level, required_hours, required_days, requires_contribution = _GATES[action]
    if action not in ('create_community',):
        required_level = max(required_level, minimum_level)
    required_xp = minimum_xp(required_level)

    profile = db.execute(select(ProgressionProfile).where(
        ProgressionProfile.user_id == user_id)).fetchone()
    current_xp = profile['xp'] if profile is not None else 0
    current_level = level_progress(current_xp).level
    first_contribution_at = (as_utc(profile['first_contribution_at'])
        if profile is not None and profile['first_contribution_at'] is not None else None)
    full_cap_days = _full_cap_days(db, user_id) if required_days else 0
    hours_remaining = float(required_hours) if requires_contribution else 0.0
    if first_contribution_at is not None and requires_contribution:
        elapsed = as_utc(now) - first_contribution_at
        hours_remaining = max(0.0, (timedelta(hours=required_hours) - elapsed).total_seconds() / 3600)

    reason = None
    if first_contribution_at is None and requires_contribution:
        reason = 'no_contribution'
    elif hours_remaining > 0:
        reason = 'time'
    elif current_xp < required_xp:
        reason = 'xp'
    elif current_level < required_level:
        reason = 'level'
    elif full_cap_days < required_days:
        reason = 'cap_days'

    return AccessDecision(reason is None, reason, current_xp, required_xp,
        current_level, required_level, first_contribution_at, full_cap_days,
        round(hours_remaining, 2))
