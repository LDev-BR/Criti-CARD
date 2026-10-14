"""Read-only template adapters and discrete progression notices."""
from flask import flash, has_request_context

from .queries import public_styles


def attach_public_styles(cards):
    styles = public_styles([card['author_id'] for card in cards])
    for card in cards:
        card['progression_style'] = styles.get(card['author_id'],{})
    return cards


def notice_message(notice):
    if notice is None:
        return None
    count = len(notice.achievement_slugs)+len(notice.reward_slugs)
    return f'Jornada: nível {notice.level_after}. {count} desbloqueios disponíveis.'


def announce(notice):
    message = notice_message(notice)
    if message and has_request_context():
        flash(message,'success')
    return message


def init_app(app):
    app.context_processor(lambda: {'progression_notice_message': notice_message})
