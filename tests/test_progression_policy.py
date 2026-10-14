from datetime import datetime, timedelta, timezone

import pytest

from criticard.progression.policy import minimum_xp, level_progress, week_key, day_key, tenure_milestones
from criticard.progression.catalog import reward_spec


@pytest.mark.parametrize('level,xp', [(1,0),(2,125),(3,250),(4,375),(5,500),(6,600),
    (11,1100),(21,2125),(31,3375),(41,4650),(51,6150),(61,7700),(71,9700),
    (81,11750),(91,14250),(100,16500),(101,16800),(120,22500),(121,22850)])
def test_level_thresholds(level, xp):
    assert minimum_xp(level) == xp
    assert level_progress(xp).level == level
    assert level_progress(xp + 1).level == level
    if xp:
        assert level_progress(xp - 1).level == level - 1


def test_progress_and_unbounded_levels():
    assert level_progress(499).level == 4
    assert level_progress(500).level == 5
    assert level_progress(599).level == 5
    assert level_progress(600).level == 6
    assert level_progress(999).tier_name == 'Iniciante'
    assert level_progress(1100).tier_name == 'Aprendiz'
    assert level_progress(10**15).tier_name == 'Lendário'
    assert level_progress(124).xp_to_next_level == 1


@pytest.mark.parametrize('value', [True, False, -1, 1.5, '50', None])
def test_invalid_xp_is_rejected(value):
    with pytest.raises(ValueError):
        level_progress(value)


@pytest.mark.parametrize('value', [True, 0, -1, 1.5, '2', None])
def test_invalid_level_is_rejected(value):
    with pytest.raises(ValueError):
        minimum_xp(value)


def test_calendar_boundaries():
    assert week_key(datetime(2021,1,1)) == '2020-53'
    assert week_key(datetime(2021,1,4)) == '2021-01'
    local = datetime(2026,10,11,23,30,tzinfo=timezone(timedelta(hours=-3)))
    assert day_key(local) == '2026-10-12'
    assert tenure_milestones(datetime(2024,2,29), datetime(2025,2,28)) == (
        ('tenure:30',50), ('tenure:90',100), ('tenure:180',150), ('anniversary:1',250))
    assert tenure_milestones(datetime(2026,1,1),datetime(2025,1,1)) == ()
    assert tenure_milestones(datetime(2024,1,1),datetime(2025,12,31))[-1] == ('anniversary:2',500)


def test_catalogue_ids_are_allowlisted():
    assert reward_spec('frame_gold')['kind'] == 'frame'
    assert reward_spec('badge_level_005')['name'] == 'Jornada: nível 5'
    assert reward_spec('frame_heritage')
    assert reward_spec('badge_anniversary_2')['name'] == '2 anos de comunidade'
    for slug in ('frame_<script>', 'badge_level_004', 'badge_anniversary_0', 'badge_anniversary_01', True, None):
        assert reward_spec(slug) is None
