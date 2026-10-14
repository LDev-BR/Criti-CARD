"""Explicit friendship transitions and public, session-owned people lists."""
from sqlalchemy import and_, case, delete, exists, func, insert, or_, select, update

from ..db import get_db
from ..models import User, utcnow
from ..validation import storable_text
from .models import Block, Follow, Friend, Notification
from .service import SocialError, _insert_once, _lock_people, _require, users_blocked

TABS = ('friends', 'incoming', 'outgoing', 'followers', 'following', 'discover')
PAGE_SIZE = 24


def _identifier(value):
    if type(value) is not int or not 1 <= value <= 2**63 - 1:
        raise SocialError('Pessoa não encontrada.', 404)
    return value


def _friend_pair(first_id, second_id):
    low, high = sorted((first_id, second_id))
    return and_(Friend.user_low_id == low, Friend.user_high_id == high)


def _state(record, viewer_id):
    if record is None:
        return {'state': 'none', 'id': None}
    return {'state': 'friends' if record['status'] == 'accepted' else
        ('outgoing' if record['requested_by'] == viewer_id else 'incoming'), 'id': record['id']}


def relationship(viewer_id, target_id):
    """Return the explicit friendship state; anonymous/self pairs have no state."""
    if viewer_id is None or viewer_id == target_id:
        return {'state': 'none', 'id': None}
    _identifier(viewer_id)
    _identifier(target_id)
    if users_blocked(viewer_id, target_id):
        return {'state': 'none', 'id': None}
    record = get_db().execute(select(Friend.__table__).where(_friend_pair(viewer_id, target_id))).fetchone()
    return _state(record, viewer_id)


def _notify_friend(record, recipient_id, actor_id, kind):
    from ..settings.service import get_preferences
    preference = {'friend_request': 'notify_friend_requests', 'friend_accept': 'notify_friend_accepts'}[kind]
    if not get_preferences(recipient_id)[preference]:
        return None
    # A new invitation after cancellation is a new event. Friendship identities
    # cannot be reused on SQLite, so each round has its own notification key.
    return _insert_once(Notification, {
        'recipient_id': recipient_id, 'actor_id': actor_id, 'kind': kind,
        'event_key': f'{kind}:{record["id"]}', 'created_at': utcnow()}, ['event_key'])


def _clear_request_notice(friend_id):
    get_db().execute(delete(Notification).where(Notification.kind == 'friend_request',
        Notification.event_key == f'friend_request:{friend_id}'))


def remove_friendship_for_block(first_id, second_id):
    """Called inside the block transaction after both participant locks."""
    db = get_db()
    record = db.execute(select(Friend.id).where(_friend_pair(first_id, second_id))).fetchone()
    if record:
        _clear_request_notice(record['id'])
        db.execute(delete(Friend).where(Friend.id == record['id']))


def change_friendship(user_id, target_id, action):
    """Perform one participant-authorized transition, without changing follows."""
    _identifier(user_id)
    _identifier(target_id)
    if user_id == target_id:
        raise SocialError('Você não pode adicionar a si mesmo.')
    if not isinstance(action, str) or action not in ('request', 'accept', 'decline', 'cancel', 'remove'):
        raise SocialError('Escolha uma ação de amizade válida.')
    db = get_db()
    with db:
        # SQLite acquires a writer reservation before reads; PostgreSQL locks
        # both users in id order. Blocking uses this same serialization point.
        _lock_people(user_id, target_id)
        actor = _require(User, user_id)
        target = _require(User, target_id)
        if actor['active'] != 1:
            raise SocialError('Esta conta está indisponível.', 403)
        if target['active'] != 1:
            raise SocialError('Pessoa não encontrada.', 404)
        if users_blocked(user_id, target_id):
            raise SocialError('Esta interação está indisponível por um bloqueio.', 403)
        record = db.execute(select(Friend.__table__).where(_friend_pair(user_id, target_id))).fetchone()
        if action == 'request':
            if record is None:
                from ..settings.service import get_preferences
                policy = get_preferences(target_id)['friend_request_policy']
                target_follows = db.execute(select(Follow.id).where(
                    Follow.user_id == target_id, Follow.target_id == user_id)).scalar() is not None
                if policy == 'nobody' or (policy == 'following' and not target_follows):
                    raise SocialError('Esta pessoa não está recebendo pedidos de amizade.', 403)
                low, high = sorted((user_id, target_id))
                now = utcnow()
                identity = db.execute(insert(Friend).values(user_low_id=low, user_high_id=high,
                    requested_by=user_id, status='pending', created_at=now, updated_at=now)
                    .returning(Friend.id)).scalar()
                record = {'id': identity, 'status': 'pending', 'requested_by': user_id}
                _notify_friend(record, target_id, user_id, 'friend_request')
            # Opposite-direction requests are intentionally never acceptance.
        elif record is None:
            if action == 'accept':
                raise SocialError('Não há solicitação para aceitar.')
        else:
            sender = record['requested_by'] == user_id
            if action in ('accept', 'decline') and sender:
                raise SocialError('Somente o destinatário pode responder ao convite.', 403)
            if action == 'cancel' and not sender:
                raise SocialError('Somente o remetente pode cancelar o convite.', 403)
            if action == 'accept':
                if record['status'] == 'pending':
                    now = utcnow()
                    db.execute(update(Friend).where(Friend.id == record['id'])
                        .values(status='accepted', accepted_at=now, updated_at=now))
                    _clear_request_notice(record['id'])
                    _notify_friend(record, target_id, user_id, 'friend_accept')
                    record['status'] = 'accepted'
            else:
                required_status = 'accepted' if action == 'remove' else 'pending'
                if record['status'] != required_status:
                    raise SocialError('Esta ação não está disponível para a amizade atual.')
                _clear_request_notice(record['id'])
                db.execute(delete(Friend).where(Friend.id == record['id']))
                record = None
        # The response describes the mutation under the same locks. Another
        # transaction cannot change the relationship between write and result.
        result = _state(record, user_id)
    return result


def _visible_people(user_id):
    blocked = exists(select(Block.id).where(or_(
        and_(Block.user_id == user_id, Block.target_id == User.id),
        and_(Block.user_id == User.id, Block.target_id == user_id))))
    return and_(User.id != user_id, User.active == 1, ~blocked)


def _tab_conditions(user_id):
    pair = or_(and_(Friend.user_low_id == user_id, Friend.user_high_id == User.id),
               and_(Friend.user_high_id == user_id, Friend.user_low_id == User.id))
    def friendship(status, sender=None):
        conditions = [pair, Friend.status == status]
        if sender is not None:
            conditions.append(Friend.requested_by == user_id if sender else Friend.requested_by != user_id)
        return exists(select(Friend.id).where(*conditions).correlate(User))
    return {
        'friends': friendship('accepted'), 'incoming': friendship('pending', False),
        'outgoing': friendship('pending', True),
        'followers': exists(select(Follow.id).where(Follow.user_id == User.id,
            Follow.target_id == user_id).correlate(User)),
        'following': exists(select(Follow.id).where(Follow.user_id == user_id,
            Follow.target_id == User.id).correlate(User)),
        'discover': True,
    }


def connection_counts(user_id):
    _require(User, user_id)
    conditions = _tab_conditions(user_id)
    columns = [func.coalesce(func.sum(case((conditions[tab], 1), else_=0)), 0).label(tab)
               for tab in TABS if tab != 'discover'] + [func.count().label('discover')]
    return dict(get_db().execute(select(*columns).select_from(User).where(_visible_people(user_id))).fetchone())


def incoming_request_count(user_id):
    """One query for the global navigation's private request counter."""
    _identifier(user_id)
    return get_db().execute(select(func.count()).select_from(User).where(
        _visible_people(user_id), _tab_conditions(user_id)['incoming'])).scalar()


def list_connections(user_id, tab='friends', query='', page=1):
    """Return only public person fields, with batched follow/friendship states."""
    if not isinstance(tab, str) or tab not in TABS:
        raise SocialError('Lista de conexões não encontrada.', 404)
    if not storable_text(query) or len(query) > 200:
        raise SocialError('Busque por um nome ou username de até 200 caracteres.')
    if type(page) is not int or page > 1_000_000:
        raise SocialError('Página de conexões não encontrada.', 404)
    page = max(1, page)
    query = query.strip()
    counts = connection_counts(user_id)
    db = get_db()
    conditions = [_visible_people(user_id), _tab_conditions(user_id)[tab]]
    if query:
        search_query = query[1:] if query.startswith('@') and len(query) > 1 else query
        pattern = '%' + search_query.casefold().replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
        if db.dialect == 'sqlite':
            searchable = [func.casefold(User.username), func.casefold(User.nome), func.casefold(User.apelido)]
        else:
            searchable = [func.lower(User.username), func.coalesce(User.search_name, func.lower(User.nome)),
                          func.lower(User.apelido)]
        conditions.append(or_(*(column.like(pattern, escape='\\') for column in searchable)))
    total = db.execute(select(func.count()).select_from(User).where(*conditions)).scalar()
    pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    if page > pages:
        raise SocialError('Página de conexões não encontrada.', 404)
    pair = or_(and_(Friend.user_low_id == user_id, Friend.user_high_id == User.id),
               and_(Friend.user_high_id == user_id, Friend.user_low_id == User.id))
    records = db.execute(select(User.id, User.username, User.nome, User.apelido, User.about, User.imagem,
        Follow.id.label('follow_id'), Friend.id.label('friend_id'), Friend.status, Friend.requested_by)
        .select_from(User).outerjoin(Follow, and_(Follow.user_id == user_id, Follow.target_id == User.id))
        .outerjoin(Friend, pair).where(*conditions).order_by(func.lower(User.nome), User.id)
        .limit(PAGE_SIZE).offset((page - 1) * PAGE_SIZE)).fetchall()
    people = []
    for record in records:
        person = {key: record[key] for key in ('id', 'username', 'nome', 'apelido', 'about', 'imagem')}
        person['following'] = record['follow_id'] is not None
        person['friendship'] = _state({'id': record['friend_id'], 'status': record['status'],
            'requested_by': record['requested_by']} if record['friend_id'] is not None else None, user_id)
        people.append(person)
    return {'people': people, 'total': total, 'page': page, 'pages': pages,
            'query': query, 'tab': tab, 'counts': counts}
