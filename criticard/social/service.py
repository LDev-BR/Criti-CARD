"""Social rules shared by HTTP routes, templates and private chat."""
from flask import g, has_request_context
from sqlalchemy import and_, delete, exists, func, insert, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from ..db import get_db
from ..models import Card, Category, User, Work, utcnow
from ..validation import storable_text
from .models import Block, CardLike, CategoryFollow, Comment, Follow, Notification, Report, WorkFollow
from .errors import SocialError


def _require(model, identity, *, archived_owner_id=None):
    if type(identity) is not int or not 1 <= identity <= 2**63 - 1:
        raise SocialError('Não encontramos este registro.', 404)
    record = get_db().execute(select(model.__table__).where(model.id == identity)).fetchone()
    if record is None:
        raise SocialError('Não encontramos este registro.', 404)
    if model is Card and record['archived'] and record['author_id'] != archived_owner_id:
        raise SocialError('Não encontramos este registro.', 404)
    return record


def _pair(first_id, second_id):
    return or_(and_(Block.user_id == first_id, Block.target_id == second_id),
               and_(Block.user_id == second_id, Block.target_id == first_id))


def users_blocked(first_id, second_id):
    """Whether either person blocked the other; safe for HTTP and Socket.IO."""
    if first_id is None or second_id is None or first_id == second_id:
        return False
    return get_db().execute(select(Block.id).where(_pair(first_id, second_id)).limit(1)).scalar() is not None


def _lock_people(first_id, second_id):
    # All social writes acquire the same ordered user locks on PostgreSQL. This
    # makes blocking and a simultaneous new interaction serialize consistently.
    db = get_db()
    if db.dialect == 'sqlite':
        # SQLite ignores FOR UPDATE. Reserve its writer before relationship
        # reads so simultaneous invitations and blocks observe committed state.
        db.execute(update(User).where(User.id.in_([first_id, second_id]))
                   .values(session_version=User.session_version))
    else:
        db.execute(select(User.id).where(User.id.in_([first_id, second_id]))
                   .order_by(User.id).with_for_update()).fetchall()


def _allowed(first_id, second_id):
    _lock_people(first_id, second_id)
    if users_blocked(first_id, second_id):
        raise SocialError('Esta interação está indisponível por um bloqueio.', 403)


def _insert_once(model, values, columns):
    db = get_db()
    dialect_insert = pg_insert if db.dialect == 'postgresql' else sqlite_insert
    return db.execute(dialect_insert(model).values(**values).on_conflict_do_nothing(
        index_elements=columns).returning(model.id)).scalar()


def notify(recipient_id, actor_id, kind, card_id=None, comment_id=None):
    """Persist an event in the current transaction, with no implicit commit.

    Like/follow retries and re-adds reuse their event key; each comment has its
    own identity. Deleting a referenced comment does not alter the event key.
    """
    if recipient_id == actor_id or recipient_id is None:
        return None
    if not isinstance(kind, str) or not 1 <= len(kind) <= 32:
        raise SocialError('Tipo de notificação inválido.')
    from ..settings.service import get_preferences
    preference = {'like': 'notify_likes', 'comment': 'notify_comments', 'follow': 'notify_follows'}.get(kind)
    if preference and not get_preferences(recipient_id)[preference]:
        return None
    key = f'{kind}:{recipient_id}:{actor_id}:{card_id or 0}:{comment_id or 0}'
    return _insert_once(Notification, dict(recipient_id=recipient_id, actor_id=actor_id,
        kind=kind, card_id=card_id, comment_id=comment_id, event_key=key, created_at=utcnow()), ['event_key'])


def card_social_state(card_ids, viewer_id=None):
    """Return {card_id: {liked, like_count, comment_count}}, including zeros."""
    ids = list(dict.fromkeys(card_ids))
    state = {identity: dict(liked=False, like_count=0, comment_count=0) for identity in ids}
    if not ids:
        return state
    db = get_db()
    for model, key in ((CardLike, 'like_count'), (Comment, 'comment_count')):
        statement = select(model.card_id, func.count().label('total')).where(model.card_id.in_(ids))
        if model is Comment and viewer_id is not None:
            statement = statement.where(~exists(select(Block.id).where(_pair(viewer_id, Comment.author_id))))
        for row in db.execute(statement.group_by(model.card_id)).fetchall():
            state[row['card_id']][key] = row['total']
    if viewer_id is not None:
        for row in db.execute(select(CardLike.card_id).where(CardLike.card_id.in_(ids),
                              CardLike.user_id == viewer_id)).fetchall():
            state[row['card_id']]['liked'] = True
    return state


def set_like(user_id, card_id, liked):
    db = get_db()
    with db:
        card = _require(Card, card_id)
        if liked:
            _allowed(user_id, card['author_id'])
            created = _insert_once(CardLike, dict(user_id=user_id, card_id=card_id, created_at=utcnow()),
                                   ['user_id', 'card_id'])
            if created:
                notify(card['author_id'], user_id, 'like', card_id)
        else:
            db.execute(delete(CardLike).where(CardLike.user_id == user_id, CardLike.card_id == card_id))
    return card_social_state([card_id], user_id)[card_id]


def _body(value, label='Comentário'):
    if not storable_text(value) or not 1 <= len(value.strip()) <= 2000:
        raise SocialError(f'{label} deve ter entre 1 e 2000 caracteres.')
    return value.strip()


def comments_for_card(card_id, page=1, *, archived_owner_id=None):
    _require(Card, card_id, archived_owner_id=archived_owner_id)
    db = get_db()
    conditions = [Comment.card_id == card_id]
    viewer = getattr(g, 'user', None) if has_request_context() else None
    if viewer is not None:
        conditions.append(~exists(select(Block.id).where(_pair(viewer['id'], Comment.author_id))))
    total = db.execute(select(func.count()).select_from(Comment).where(*conditions)).scalar()
    page = max(1, page)
    if page > max(1, (total + 29) // 30):
        raise SocialError('Página de comentários não encontrada.', 404)
    comments = db.execute(select(Comment.__table__, User.username, User.nome).join(User, User.id == Comment.author_id)
        .where(*conditions).order_by(Comment.id.desc()).limit(30).offset((page - 1) * 30)).fetchall()
    return {'comments': comments, 'total': total, 'page': page, 'pages': max(1, (total + 29) // 30)}


def create_comment(user_id, card_id, body):
    from ..progression.service import lock_owner, record_action, require_owner_session

    body = _body(body)
    db = get_db()
    with db:
        card = _require(Card, card_id)
        _allowed(user_id, card['author_id'])
        require_owner_session(lock_owner(db,user_id))
        comment_id = db.execute(insert(Comment).values(author_id=user_id, card_id=card_id, body=body,
                     created_at=utcnow(), updated_at=utcnow()).returning(Comment.id)).scalar()
        notify(card['author_id'], user_id, 'comment', card_id, comment_id)
        record_action(db,user_id,'activity',utcnow())
    return _require(Comment, comment_id)


def edit_comment(user_id, comment_id, body):
    body = _body(body)
    db = get_db()
    with db:
        comment = _require(Comment, comment_id)
        if comment['author_id'] != user_id:
            raise SocialError('Só o autor pode editar este comentário.', 403)
        card = _require(Card, comment['card_id'])
        _allowed(user_id, card['author_id'])
        db.execute(update(Comment).where(Comment.id == comment_id).values(body=body, updated_at=utcnow()))
    return _require(Comment, comment_id)


def delete_comment(user_id, comment_id, admin=False):
    db = get_db()
    with db:
        comment = _require(Comment, comment_id)
        if comment['author_id'] != user_id and not (admin and _require(User, user_id)['admin'] == 1):
            raise SocialError('Você não pode excluir este comentário.', 403)
        db.execute(delete(Comment).where(Comment.id == comment_id))
    return comment['card_id']


def user_social_state(user_id, viewer_id=None):
    from .connections import connection_counts, relationship
    _require(User, user_id)
    db = get_db()
    state = {'follower_count': db.execute(select(func.count()).select_from(Follow)
        .where(Follow.target_id == user_id)).scalar(), 'following_count': db.execute(select(func.count()).select_from(Follow)
        .where(Follow.user_id == user_id)).scalar(), 'following': False, 'blocked': False,
        'interaction_blocked': users_blocked(viewer_id, user_id),
        'friend_count': connection_counts(user_id)['friends'],
        'friendship': relationship(viewer_id, user_id)}
    if viewer_id is not None:
        state['following'] = db.execute(select(Follow.id).where(Follow.user_id == viewer_id,
            Follow.target_id == user_id)).scalar() is not None
        state['blocked'] = db.execute(select(Block.id).where(Block.user_id == viewer_id,
            Block.target_id == user_id)).scalar() is not None
    return state


def set_follow(user_id, target_id, following):
    if user_id == target_id:
        raise SocialError('Você não pode seguir a si mesmo.')
    db = get_db()
    with db:
        _require(User, target_id)
        if following:
            _allowed(user_id, target_id)
            created = _insert_once(Follow, dict(user_id=user_id, target_id=target_id, created_at=utcnow()),
                                   ['user_id', 'target_id'])
            if created:
                notify(target_id, user_id, 'follow')
        else:
            db.execute(delete(Follow).where(Follow.user_id == user_id, Follow.target_id == target_id))
    return user_social_state(target_id, user_id)


def work_follow_states(work_ids, user_id=None):
    ids = list(dict.fromkeys(work_ids))
    result = {identity: False for identity in ids}
    if user_id is not None and ids:
        for row in get_db().execute(select(WorkFollow.work_id).where(
            WorkFollow.user_id == user_id, WorkFollow.work_id.in_(ids))).fetchall():
            result[row['work_id']] = True
    return result


def category_follow_states(category_ids, user_id=None):
    ids = list(dict.fromkeys(category_ids))
    result = {identity: False for identity in ids}
    if user_id is not None and ids:
        for row in get_db().execute(select(CategoryFollow.category_id).where(
            CategoryFollow.user_id == user_id, CategoryFollow.category_id.in_(ids))).fetchall():
            result[row['category_id']] = True
    return result


def set_work_follow(user_id, work_id, following):
    work = _require(Work, work_id)
    if following and work['active'] != 1:
        raise SocialError('Esta obra nÃ£o estÃ¡ disponÃ­vel para seguir.', 404)
    db = get_db()
    with db:
        if following:
            _insert_once(WorkFollow, {'user_id': user_id, 'work_id': work_id,
                'created_at': utcnow()}, ['user_id','work_id'])
        else:
            db.execute(delete(WorkFollow).where(WorkFollow.user_id == user_id,
                WorkFollow.work_id == work_id))
    return {'work_id': work_id, 'following': bool(following)}


def set_category_follow(user_id, category_id, following):
    _require(Category, category_id)
    db = get_db()
    with db:
        if following:
            _insert_once(CategoryFollow, {'user_id': user_id, 'category_id': category_id,
                'created_at': utcnow()}, ['user_id','category_id'])
        else:
            db.execute(delete(CategoryFollow).where(CategoryFollow.user_id == user_id,
                CategoryFollow.category_id == category_id))
    return {'category_id': category_id, 'following': bool(following)}


def set_block(user_id, target_id, blocked):
    from .connections import remove_friendship_for_block
    if any(type(identity) is not int or not 1 <= identity <= 2**63 - 1
           for identity in (user_id, target_id)):
        raise SocialError('Não encontramos este registro.', 404)
    if user_id == target_id:
        raise SocialError('Você não pode bloquear a si mesmo.')
    db = get_db()
    with db:
        _lock_people(user_id, target_id)
        _require(User, target_id)
        if blocked:
            _insert_once(Block, dict(user_id=user_id, target_id=target_id, created_at=utcnow()), ['user_id', 'target_id'])
            db.execute(delete(Follow).where(or_(and_(Follow.user_id == user_id, Follow.target_id == target_id),
                                               and_(Follow.user_id == target_id, Follow.target_id == user_id))))
            remove_friendship_for_block(user_id, target_id)
        else:
            db.execute(delete(Block).where(Block.user_id == user_id, Block.target_id == target_id))
    return user_social_state(target_id, user_id)


def create_report(user_id, target_type, target_id, reason):
    if not isinstance(target_type, str) or type(target_id) is not int or not 1 <= target_id <= 2**63 - 1:
        raise SocialError('Informe um alvo válido para a denúncia.')
    model = {'card': Card, 'comment': Comment, 'user': User}.get(target_type)
    community_target = target_type in ('community_post', 'community_comment')
    if target_type == 'chat_message':
        from ..chat.models import Conversation, Message
        from ..chat.service import ChatError, membership
        message = get_db().execute(select(Message.__table__).join(Conversation,
            Conversation.id == Message.conversation_id).where(Message.id == target_id,
                Conversation.kind == 'group')).fetchone()
        if message is None:
            raise SocialError('Mensagem de grupo não encontrada.', 404)
        try:
            membership(user_id, message['conversation_id'])
        except ChatError as error:
            raise SocialError(str(error), error.status) from None
    elif model is None and not community_target:
        raise SocialError('Escolha um card, comentário, mensagem de grupo, publicação ou usuário para denunciar.')
    reason = _body(reason, 'Motivo')
    db = get_db()
    with db:
        if model is not None:
            _require(model, target_id)
        elif community_target:
            _community_report_target(target_type, target_id, user_id)
        identity = db.execute(insert(Report).values(reporter_id=user_id, target_type=target_type,
            target_id=target_id, reason=reason, status='pending', created_at=utcnow()).returning(Report.id)).scalar()
    return _require(Report, identity)


def _community_report_target(target_type, target_id, user_id):
    from ..communities.models import Community, CommunityComment, CommunityMembership, CommunityPost
    db = get_db()
    if target_type == 'community_post':
        row = db.execute(select(CommunityPost.id, CommunityPost.community_id, CommunityPost.author_id,
            Community.mode.label('mode')).join(Community, Community.id == CommunityPost.community_id)
            .where(CommunityPost.id == target_id, Community.archived == 0)).fetchone()
    else:
        row = db.execute(select(CommunityComment.id, CommunityPost.community_id, CommunityComment.author_id,
            Community.mode.label('mode')).join(CommunityPost, CommunityPost.id == CommunityComment.post_id)
            .join(Community, Community.id == CommunityPost.community_id)
            .where(CommunityComment.id == target_id, Community.archived == 0)).fetchone()
    if row is None:
        raise SocialError('Publicação ou comentário de comunidade não encontrado.', 404)
    if row['mode'] == 'closed' and db.execute(select(CommunityMembership.user_id).where(
        CommunityMembership.community_id == row['community_id'],
        CommunityMembership.user_id == user_id)).scalar() is None:
        raise SocialError('Entre na comunidade para denunciar este conteúdo.', 403)
    if users_blocked(user_id, row['author_id']):
        raise SocialError('PublicaÃ§Ã£o ou comentÃ¡rio nÃ£o encontrado.', 404)
    return row


def moderation_reports(page=1):
    page = max(1, page)
    db = get_db()
    total = db.execute(select(func.count()).select_from(Report)).scalar()
    if page > max(1, (total + 29) // 30):
        raise SocialError('Página de denúncias não encontrada.', 404)
    records = db.execute(select(Report.__table__, User.username.label('reporter_username')).outerjoin(User,
        User.id == Report.reporter_id).order_by(Report.status, Report.id.desc()).limit(30).offset((page - 1) * 30)).fetchall()
    enriched = []
    from ..chat.models import Message
    from ..communities.models import Community, CommunityComment, CommunityPost
    for record in records:
        preview = None
        if record['target_type'] == 'chat_message':
            message = db.execute(select(Message.body, Message.redacted_at).where(
                Message.id == record['target_id'])).fetchone()
            if message:
                preview = 'Mensagem removida pela modera\u00e7\u00e3o.' if message['redacted_at'] else message['body'][:240]
        elif record['target_type'] == 'community_post':
            post = db.execute(select(Community.name, CommunityPost.title, CommunityPost.body)
                .join(Community, Community.id == CommunityPost.community_id).where(
                    CommunityPost.id == record['target_id'])).fetchone()
            if post:
                preview = (post['name'] + ' · ' + post['title'] + ': ' + post['body'])[:300]
        elif record['target_type'] == 'community_comment':
            comment = db.execute(select(Community.name, CommunityComment.body)
                .join(CommunityPost, CommunityPost.id == CommunityComment.post_id)
                .join(Community, Community.id == CommunityPost.community_id).where(
                    CommunityComment.id == record['target_id'])).fetchone()
            if comment:
                preview = (comment['name'] + ' · ' + comment['body'])[:300]
        enriched.append(dict(record,target_preview=preview))
    return {'reports': enriched, 'total': total, 'page': page, 'pages': max(1, (total + 29) // 30)}


def resolve_report(admin_id, report_id):
    # Keep the service permission check: routes are not the only possible caller.
    if _require(User, admin_id)['admin'] != 1:
        raise SocialError('Esta ação é reservada à moderação.', 403)
    db = get_db()
    with db:
        _require(Report, report_id)
        db.execute(update(Report).where(Report.id == report_id, Report.status == 'pending')
            .values(status='resolved', resolved_at=utcnow(), resolved_by=admin_id))
    return _require(Report, report_id)


def unread_count(user_id):
    return get_db().execute(select(func.count()).select_from(Notification).where(
        Notification.recipient_id == user_id, Notification.read_at.is_(None))).scalar()


def notifications_for_user(user_id, page=1, **filters):
    from .notifications import for_user
    return for_user(user_id, page, **filters)


def mark_notification_read(user_id, notification_id=None):
    from .notifications import mark_read
    return mark_read(user_id, notification_id)
