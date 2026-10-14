"""Integer-only level curve and UTC calendar; independent of Flask/storage."""
from datetime import timezone

from .catalog import TIERS
from .types import LevelProgress


def minimum_xp(level):
    if type(level) is not int or level < 1:
        raise ValueError('O nível deve ser um inteiro positivo.')
    total = min(level - 1, 4) * 125
    if level >= 6:
        total += 100
    total += sum(max(0, min(level, hi) - lo + 1) * cost for lo, hi, cost in
        ((7,20,100),(21,40,125),(41,60,150),(61,80,200),(81,100,250)))
    if level > 100:
        blocks, remainder = divmod(level-100,20)
        total += 20*(blocks*300 + 50*blocks*(blocks-1)//2) + remainder*(300+50*blocks)
    return total


def level_progress(total_xp):
    if type(total_xp) is not int or total_xp < 0:
        raise ValueError('O XP deve ser um inteiro não negativo.')
    low, high = 1, 2
    while minimum_xp(high) <= total_xp:
        high *= 2
    while low+1 < high:
        mid = (low+high)//2
        if minimum_xp(mid) <= total_xp:
            low = mid
        else:
            high = mid
    tier = TIERS[min((low-1)//10,9)]
    next_xp = minimum_xp(low+1)
    return LevelProgress(low,total_xp,total_xp-minimum_xp(low),next_xp-total_xp,
        next_xp,tier['slug'],tier['name'])


def as_utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def week_key(now):
    year, week, _ = as_utc(now).isocalendar()
    return f'{year}-{week:02}'


def day_key(now):
    return as_utc(now).date().isoformat()


def tenure_milestones(since,now):
    days = (as_utc(now)-as_utc(since)).days
    milestones = [(f'tenure:{n}',xp) for n,xp in ((30,50),(90,100),(180,150)) if days>=n]
    milestones.extend((f'anniversary:{year}',250 if year==1 else 500) for year in range(1,days//365+1))
    return tuple(milestones)
