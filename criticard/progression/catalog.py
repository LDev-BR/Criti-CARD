"""Allowlisted cosmetics: no user supplied CSS or asset paths."""
import re
from types import MappingProxyType

RULE_VERSION = 1
DAILY_CAP = 200
TIERS = tuple(MappingProxyType(dict(slug=slug, name=name, level=1+i*10, material=material))
    for i, (slug, name, material) in enumerate((
        ('newcomer','Iniciante','classic'), ('apprentice','Aprendiz','slate'),
        ('explorer','Explorador','bronze'), ('enthusiast','Entusiasta','copper'),
        ('critic','Crítico','silver'), ('analyst','Analista','sapphire'),
        ('curator','Curador','gold'), ('specialist','Especialista','platinum'),
        ('master','Mestre','obsidian'), ('legendary','Lendário','obsidian_gold'))))
MATERIAL_NAMES = MappingProxyType(dict(classic='Clássico',slate='Ardósia',bronze='Bronze',
    copper='Cobre',silver='Prata',sapphire='Safira',gold='Ouro',platinum='Platina',
    obsidian='Obsidiana',obsidian_gold='Obsidiana e ouro',aurora='Aurora',heritage='Patrimônio'))
ACHIEVEMENTS = MappingProxyType({
    'first_review': ('Primeira crítica','Publique uma crítica de uma obra.',1),
    'reviews_5': ('Voz da comunidade','Publique críticas de 5 obras.',5),
    'reviews_10': ('Coleção de opiniões','Publique críticas de 10 obras.',10),
    'categories_3': ('Olhar plural','Publique críticas em 3 categorias.',3),
    'completed_5': ('Cinco jornadas','Conclua 5 obras no backlog.',5),
    'weeks_4': ('Presença constante','Participe em 4 semanas, sem precisar de sequência.',4),
    'pioneer': ('Pioneiro','Conta anterior ao sistema de jornada.',1),
    'tenure_30': ('Um mês por aqui','Complete 30 dias na comunidade.',30),
    'tenure_90': ('Raízes na comunidade','Complete 90 dias na comunidade.',90),
    'tenure_180': ('Seis meses de histórias','Complete 180 dias na comunidade.',180),
})


def achievement_spec(slug):
    if not isinstance(slug,str):
        return None
    if slug in ACHIEVEMENTS:
        name, description, target = ACHIEVEMENTS[slug]
        return dict(slug=slug,name=name,description=description,target=target)
    if re.fullmatch(r'level_(?:00[5]|0[1-9][05]|100)',slug):
        level = int(slug[6:])
        return dict(slug=slug,name=f'Jornada: nível {level}' if level<100 else 'Centenário',
            description=f'Alcance o nível {level}.',target=level)
    if re.fullmatch(r'anniversary_[1-9][0-9]{0,3}',slug):
        year = int(slug[12:])
        return dict(slug=slug,name=f'{year} ano de comunidade' if year==1 else f'{year} anos de comunidade',
            description=f'Complete {year*365} dias na comunidade.',target=year*365)
    return None


def _rewards():
    values = {}
    for tier in TIERS:
        values['title_'+tier['slug']] = dict(kind='title',name=tier['name'],level=tier['level'])
        for kind in ('frame','card'):
            values[kind+'_'+tier['material']] = dict(kind=kind,name=MATERIAL_NAMES[tier['material']],level=tier['level'])
    values['frame_aurora'] = dict(kind='frame',name='Aurora',achievement='tenure_90')
    values['frame_heritage'] = dict(kind='frame',name='Patrimônio',achievement='anniversary_1')
    for slug in (*ACHIEVEMENTS, *(f'level_{n:03}' for n in range(5,101,5))):
        values['badge_'+slug] = dict(kind='badge',name=achievement_spec(slug)['name'],achievement=slug)
    return MappingProxyType({k:MappingProxyType(dict(slug=k,**v)) for k,v in values.items()})


REWARDS = _rewards()


def reward_spec(slug):
    if not isinstance(slug,str):
        return None
    if slug in REWARDS:
        return dict(REWARDS[slug])
    if slug.startswith('badge_anniversary_'):
        achievement = achievement_spec(slug[6:])
        if achievement:
            return dict(slug=slug,kind='badge',name=achievement['name'],achievement=achievement['slug'])
    return None
