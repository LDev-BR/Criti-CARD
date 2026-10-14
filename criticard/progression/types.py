from dataclasses import dataclass


@dataclass(frozen=True)
class LevelProgress:
    level: int
    total_xp: int
    xp_into_level: int
    xp_to_next_level: int
    next_level_xp: int
    tier_slug: str
    tier_name: str


@dataclass(frozen=True)
class XpAward:
    event_id: int | None
    awarded: int
    total_xp: int
    level_before: int
    level_after: int


@dataclass(frozen=True)
class GrantChanges:
    achievements_added: tuple[str, ...] = ()
    rewards_added: tuple[str, ...] = ()
    achievements_revoked: tuple[str, ...] = ()
    rewards_revoked: tuple[str, ...] = ()


@dataclass(frozen=True)
class Notice:
    level_before: int
    level_after: int
    achievement_slugs: tuple[str, ...]
    reward_slugs: tuple[str, ...]


class ProgressionError(ValueError):
    def __init__(self, message, status=422, field=None):
        super().__init__(message)
        self.message, self.status, self.field = message, status, field
