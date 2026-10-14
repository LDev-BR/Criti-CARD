"""Owner-scoped notification queries and transactional read actions."""
from sqlalchemy import case, func, select, update
from flask import current_app, has_request_context, url_for

from ..db import get_db
from ..models import Card, User, utcnow
from ..progression.policy import as_utc
from ..progression.service import lock_owner, require_owner_session
from .errors import SocialError
from .models import Notification

KINDS = {
    'like': ('Curtidas', 'curtiu sua crítica', 'heart'),
    'comment': ('Comentários', 'comentou sua crítica', 'message'),
    'follow': ('Seguidores', 'começou a seguir você', 'user-plus'),
    'friend_request': ('Convites de amizade', 'enviou um convite de amizade', 'users'),
    'friend_accept': ('Amizades aceitas', 'aceitou seu convite de amizade', 'user-check'),
    'message': ('Mensagens', 'enviou uma mensagem', 'mail'),
}
STATES = {'all': 'Todas', 'unread': 'Não lidas', 'read': 'Lidas'}


def filters(state='all', kind='all'):
    if state not in STATES or kind not in ('all', *KINDS):
        raise SocialError('Filtro de notificações não encontrado.', 404)
    return dict(state=state, kind=kind)


def snapshot(user_id):
    row = get_db().execute(select(
        func.coalesce(func.sum(case((Notification.read_at.is_(None), 1), else_=0)), 0).label('unread_count'),
        func.coalesce(func.max(Notification.id), 0).label('latest_id'),
        func.max(Notification.created_at).label('latest_at')
    ).where(Notification.recipient_id == user_id)).fetchone()
    return dict(unread_count=row['unread_count'], latest_id=row['latest_id'],
        latest_at=as_utc(row['latest_at']).isoformat() if row['latest_at'] else None)


def _records():
    return select(Notification.__table__, User.username.label('actor_username'),
        User.nome.label('actor_name'), User.imagem.label('actor_image'),
        User.active.label('actor_active'), Card.titulo.label('card_title')) \
        .outerjoin(User, User.id == Notification.actor_id).outerjoin(Card, Card.id == Notification.card_id)


def _url(endpoint, **values):
    return url_for(endpoint, **values) if has_request_context() else current_app.url_map.bind('').build(endpoint, values)


def _present(row):
    row['created_at'] = as_utc(row['created_at'])
    if row['read_at']:
        row['read_at'] = as_utc(row['read_at'])
    row['kind_name'], row['verb'], row['icon'] = KINDS.get(row['kind'], ('Atividade', 'interagiu com você', 'bell'))
    row['target_url'] = None
    row['target_label'] = ''
    if row['kind'] in ('like', 'comment') and row['card_id']:
        row['target_url'] = _url('cards.detail', id=row['card_id']) + ('#comments' if row['kind'] == 'comment' else '')
        row['target_label'] = 'Ver crítica' if row['kind'] == 'like' else 'Ver comentário'
    elif row['kind'] in ('friend_request', 'friend_accept'):
        row['target_url'] = _url('people.connections', aba='recebidas' if row['kind'] == 'friend_request' else 'amigos')
        row['target_label'] = 'Ver solicitações' if row['kind'] == 'friend_request' else 'Ver amigos'
    elif row['kind'] == 'follow' and row['actor_username'] and row['actor_active']:
        row['target_url'] = _url('community.profile', username=row['actor_username'])
        row['target_label'] = 'Ver perfil'
    elif row['kind'] == 'message':
        row['target_url'], row['target_label'] = _url('chat.index'), 'Ver mensagens'
    return row


def for_user(user_id, page=1, *, state='all', kind='all'):
    selected = filters(state, kind)
    if type(page) is not int or not 1 <= page <= 1_000_000:
        raise SocialError('Página de notificações não encontrada.', 404)
    db = get_db()
    condition = Notification.recipient_id == user_id
    if state != 'all':
        condition &= Notification.read_at.is_(None) if state == 'unread' else Notification.read_at.is_not(None)
    if kind != 'all':
        condition &= Notification.kind == kind
    total = db.execute(select(func.count()).select_from(Notification).where(condition)).scalar()
    pages = max(1, (total + 29) // 30)
    if page > pages:
        raise SocialError('Página de notificações não encontrada.', 404)
    records = db.execute(_records().where(condition).order_by(Notification.id.desc())
        .limit(30).offset((page-1)*30)).fetchall()
    return dict(notifications=[_present(row) for row in records], total=total, page=page, pages=pages,
        filters=selected, kinds=KINDS, states=STATES, **snapshot(user_id))


def mark_read(user_id, notification_id=None):
    if notification_id is not None and (type(notification_id) is not int or not 1 <= notification_id <= 2**63-1):
        raise SocialError('Notificação não encontrada.', 404)
    db = get_db()
    target_url = None
    with db:
        require_owner_session(lock_owner(db, user_id))
        condition = Notification.recipient_id == user_id
        if notification_id is not None:
            condition &= Notification.id == notification_id
            row = db.execute(_records().where(condition)).fetchone()
            if row is None:
                raise SocialError('Notificação não encontrada.', 404)
            target_url = _present(row)['target_url']
        db.execute(update(Notification).where(condition, Notification.read_at.is_(None)).values(read_at=utcnow()))
        result = snapshot(user_id)
    return dict(**result, target_url=target_url)
