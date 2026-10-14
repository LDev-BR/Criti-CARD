"""Membership rules and publication workflows for thematic communities."""
import re
import secrets
import unicodedata

from sqlalchemy import and_, delete, exists, func, insert, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from ..db import get_db
from ..models import Category, User, Work, utcnow
from ..progression.access import evaluate_social_access
from ..social.models import Block
from ..storage import valid_image_name
from ..validation import storable_text
from .models import (Community, CommunityComment, CommunityInvite, CommunityJoinRequest,
                     CommunityMembership, CommunityPost, CommunityReaction)

THEMES = ('gold', 'rose', 'blue', 'green', 'violet', 'dark')
ICONS = ('sparkles', 'book', 'film', 'music', 'game', 'chat', 'heart', 'star')
REACTIONS = ('like', 'insightful', 'fun')


class CommunityError(ValueError):
    def __init__(self, message, status=422):
        super().__init__(message)
        self.status = status


def _identifier(value, message='Identificador inválido.'):
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise CommunityError(message)
    try:
        result = int(value)
    except (TypeError, ValueError, OverflowError):
        raise CommunityError(message) from None
    if not 1 <= result <= 2 ** 63 - 1:
        raise CommunityError(message)
    return result


def _lock_actor(db, user_id):
    from ..progression.service import lock_owner, require_owner_session
    actor = lock_owner(db, user_id)
    require_owner_session(actor)
    return actor


def _require_community(community_id=None, slug=None, *, active=True):
    if community_id is not None:
        community_id = _identifier(community_id)
    db = get_db()
    query = select(Community.__table__)
    if community_id is not None:
        query = query.where(Community.id == community_id)
    if slug is not None:
        query = query.where(Community.slug == slug)
    if active:
        query = query.where(Community.archived == 0)
    row = db.execute(query).fetchone()
    if row is None:
        raise CommunityError('Comunidade não encontrada.', 404)
    return row


def _active_member(community_id, user_id):
    return get_db().execute(select(CommunityMembership.__table__).where(
        CommunityMembership.community_id == community_id,
        CommunityMembership.user_id == user_id)).fetchone()


def _moderator(community_id, user_id):
    membership = _active_member(community_id, user_id)
    if membership is None or membership['role'] not in ('owner', 'moderator'):
        raise CommunityError('Somente a pessoa responsável ou um moderador pode fazer isso.', 403)
    return membership


def _ensure_access(user_id, action, minimum_level):
    decision = evaluate_social_access(get_db(), user_id, action, utcnow(), minimum_level=minimum_level)
    if decision.eligible:
        return decision
    if decision.reason in ('xp', 'level'):
        raise CommunityError(f'Você precisa alcançar o nível {decision.required_level} para participar.')
    raise CommunityError('Sua conta ainda não atende ao nível mínimo configurado para esta comunidade.')


def _ensure_interaction_allowed(first_id, second_id):
    from ..social.service import users_blocked
    if users_blocked(first_id, second_id):
        raise CommunityError('Esta interação está indisponível por um bloqueio.', 403)


def _insert_once(model, values, keys):
    db = get_db()
    insert_for = pg_insert if db.dialect == 'postgresql' else sqlite_insert
    partial = text("status = 'pending'") if model in (CommunityJoinRequest, CommunityInvite) else None
    return db.execute(insert_for(model).values(**values).on_conflict_do_nothing(
        index_elements=keys, index_where=partial).returning(
            model.__table__.primary_key.columns.keys()[0])).scalar()


def _slug(name):
    plain = unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode().lower()
    plain = re.sub(r'[^a-z0-9]+', '-', plain).strip('-')[:72] or 'comunidade'
    return f'{plain}-{secrets.token_hex(3)}'


def _cover_name(value):
    if value is not None and not valid_image_name(value):
        raise CommunityError('A capa da comunidade não é válida.')
    return value


def access_progress(user_id):
    return evaluate_social_access(get_db(), user_id, 'create_community', utcnow()).as_dict()


def community_index(user_id=None):
    db = get_db()
    own = CommunityMembership.__table__
    source = Community.__table__.outerjoin(Category.__table__, Category.id == Community.category_id)
    source = source.outerjoin(own, and_(own.c.community_id == Community.id,
        own.c.user_id == user_id))
    members = CommunityMembership.__table__.alias('community_member_count')
    member_count = select(func.count()).select_from(members.join(User.__table__,
        User.__table__.c.id == members.c.user_id)).where(
            members.c.community_id == Community.id, User.active == 1).scalar_subquery()
    rows = db.execute(select(Community.__table__, Category.nome.label('category_name'),
        own.c.role.label('my_role'), own.c.joined_at.label('joined_at'),
        member_count.label('member_count'))
        .select_from(source).where(Community.archived == 0)
        .order_by(Community.seeded.desc(), Community.name, Community.id)).fetchall()
    invites = []
    if user_id is not None:
        invites = db.execute(select(CommunityInvite.__table__, Community.name.label('community_name'),
            Community.slug.label('community_slug')).join(Community,
            Community.id == CommunityInvite.community_id).where(
                CommunityInvite.invitee_id == user_id, CommunityInvite.status == 'pending',
                Community.archived == 0).order_by(CommunityInvite.created_at.desc()).limit(30)).fetchall()
    return {'communities': rows, 'invites': invites}


def community_page(slug, user_id=None):
    community = _require_community(slug=slug)
    membership = _active_member(community['id'], user_id) if user_id else None
    is_private = community['mode'] == 'closed' and membership is None
    db = get_db()
    count = db.execute(select(func.count()).select_from(CommunityMembership).join(
        User, User.id == CommunityMembership.user_id).where(
            CommunityMembership.community_id == community['id'], User.active == 1)).scalar()
    pending = None
    if user_id:
        pending = db.execute(select(CommunityJoinRequest.id).where(
            CommunityJoinRequest.community_id == community['id'],
            CommunityJoinRequest.user_id == user_id,
            CommunityJoinRequest.status == 'pending')).scalar()
    result = {'community': community, 'membership': membership, 'member_count': count,
        'is_private': is_private, 'pending_request': pending, 'posts': [], 'members': [],
        'requests': [], 'work_titles': {}, 'works': []}
    if user_id:
        result['my_invites'] = db.execute(select(CommunityInvite.__table__).where(
            CommunityInvite.community_id == community['id'], CommunityInvite.invitee_id == user_id,
            CommunityInvite.status == 'pending')).fetchall()
    if is_private:
        result['community'] = dict(community, description='', cover=None, created_by=None)
        result['member_count'] = None
        return result

    blocked = None
    if user_id is not None:
        blocked = exists(select(Block.id).where(or_(and_(Block.user_id == user_id,
            Block.target_id == CommunityPost.author_id), and_(Block.target_id == user_id,
            Block.user_id == CommunityPost.author_id))))
    post_query = select(CommunityPost.__table__, User.username, User.nome, User.imagem).join(
        User, User.id == CommunityPost.author_id).where(CommunityPost.community_id == community['id'])
    if blocked is not None:
        post_query = post_query.where(~blocked)
    posts = db.execute(post_query.order_by(CommunityPost.created_at.desc(), CommunityPost.id.desc()).limit(30)).fetchall()
    result['posts'] = posts
    work_ids = [row['work_id'] for row in posts if row['work_id']]
    if work_ids:
        result['work_titles'] = {row['id']: row['titulo'] for row in db.execute(select(
            Work.id, Work.titulo).where(Work.id.in_(work_ids))).fetchall()}
    work_query = select(Work.id, Work.titulo).where(Work.active == 1)
    if community['category_id'] is not None:
        work_query = work_query.where(Work.categoria_id == community['category_id'])
    result['works'] = db.execute(work_query.order_by(Work.titulo, Work.id).limit(100)).fetchall()
    result['members'] = db.execute(select(CommunityMembership.__table__, User.username, User.nome)
        .join(User, User.id == CommunityMembership.user_id).where(
            CommunityMembership.community_id == community['id'], User.active == 1)
        .order_by(CommunityMembership.joined_at, CommunityMembership.user_id)).fetchall()
    if membership and membership['role'] in ('owner', 'moderator'):
        result['requests'] = db.execute(select(CommunityJoinRequest.__table__, User.username, User.nome)
            .join(User, User.id == CommunityJoinRequest.user_id).where(
                CommunityJoinRequest.community_id == community['id'],
                CommunityJoinRequest.status == 'pending', User.active == 1).order_by(CommunityJoinRequest.created_at)).fetchall()
    return result


def create_community(user_id, fields, cover_filename=None):
    name = fields.get('name', '').strip() if isinstance(fields.get('name'), str) else ''
    description = fields.get('description', '').strip() if isinstance(fields.get('description'), str) else ''
    mode = fields.get('mode', 'open')
    theme = fields.get('theme', 'gold')
    icon = fields.get('icon', 'sparkles')
    if not storable_text(name) or not 2 <= len(name) <= 80:
        raise CommunityError('O nome deve ter entre 2 e 80 caracteres.')
    if not storable_text(description) or len(description) > 1000:
        raise CommunityError('A descrição pode ter até 1000 caracteres.')
    if mode not in ('open', 'closed') or theme not in THEMES or icon not in ICONS:
        raise CommunityError('Escolha opções válidas de acesso e aparência.')
    try:
        minimum_level = int(fields.get('minimum_level', 1))
    except (TypeError, ValueError):
        raise CommunityError('O nível mínimo precisa ser um número inteiro.') from None
    if not 1 <= minimum_level <= 999:
        raise CommunityError('O nível mínimo deve estar entre 1 e 999.')
    cover_filename = _cover_name(cover_filename)
    db = get_db()
    with db:
        _lock_actor(db, user_id)
        decision = evaluate_social_access(db, user_id, 'create_community', utcnow())
        if not decision.eligible:
            if decision.reason == 'no_contribution':
                raise CommunityError('Faça sua primeira contribuição para iniciar os 7 dias de espera.')
            raise CommunityError('A criação de comunidades é liberada após 7 dias desde sua primeira contribuição.')
        now = utcnow()
        community_id = db.execute(insert(Community).values(slug=_slug(name), name=name,
            description=description, theme=theme, icon=icon, cover=cover_filename, mode=mode,
            minimum_level=minimum_level, created_by=user_id, seeded=0, archived=0,
            created_at=now, updated_at=now).returning(Community.id)).scalar()
        db.execute(insert(CommunityMembership).values(community_id=community_id, user_id=user_id,
            role='owner', joined_at=now))
    return _require_community(community_id=community_id)


def join_open_community(user_id, community_id):
    db = get_db()
    with db:
        _lock_actor(db, user_id)
        community = _require_community(community_id=community_id)
        if community['mode'] != 'open':
            raise CommunityError('Esta comunidade é fechada; solicite acesso ou use um convite.', 409)
        _ensure_access(user_id, 'join_open_community', community['minimum_level'])
        _insert_once(CommunityMembership, {'community_id': community_id, 'user_id': user_id,
            'role': 'member', 'joined_at': utcnow()}, ['community_id', 'user_id'])
        db.execute(delete(CommunityJoinRequest).where(CommunityJoinRequest.community_id == community_id,
            CommunityJoinRequest.user_id == user_id, CommunityJoinRequest.status == 'pending'))
    return _active_member(community_id, user_id)


def request_community_access(user_id, community_id):
    db = get_db()
    with db:
        _lock_actor(db, user_id)
        community = _require_community(community_id=community_id)
        if community['mode'] != 'closed':
            raise CommunityError('Comunidades abertas permitem entrada direta.', 409)
        if _active_member(community_id, user_id):
            return None
        invitation = db.execute(select(CommunityInvite.id).where(
            CommunityInvite.community_id == community_id, CommunityInvite.invitee_id == user_id,
            CommunityInvite.status == 'pending')).scalar()
        if invitation is not None:
            raise CommunityError('Você já recebeu um convite. Aceite-o para entrar.', 409)
        _ensure_access(user_id, 'join_closed_community', community['minimum_level'])
        _insert_once(CommunityJoinRequest, {'community_id': community_id, 'user_id': user_id,
            'status': 'pending', 'created_at': utcnow()}, ['community_id', 'user_id'])
    return get_db().execute(select(CommunityJoinRequest.__table__).where(
        CommunityJoinRequest.community_id == community_id, CommunityJoinRequest.user_id == user_id,
        CommunityJoinRequest.status == 'pending')).fetchone()


def cancel_join_request(user_id, request_id):
    request_id = _identifier(request_id)
    db = get_db()
    with db:
        _lock_actor(db, user_id)
        changed = db.execute(update(CommunityJoinRequest).where(
            CommunityJoinRequest.id == request_id, CommunityJoinRequest.user_id == user_id,
            CommunityJoinRequest.status == 'pending').values(status='cancelled', resolved_at=utcnow()))
        if changed.rowcount == 0:
            raise CommunityError('Solicitação pendente não encontrada.', 404)


def resolve_join_request(actor_id, request_id, approve):
    request_id = _identifier(request_id)
    db = get_db()
    with db:
        _lock_actor(db, actor_id)
        req = db.execute(select(CommunityJoinRequest.__table__).where(
            CommunityJoinRequest.id == request_id).with_for_update()).fetchone()
        if req is None or req['status'] != 'pending':
            raise CommunityError('Solicitação não encontrada.', 404)
        _moderator(req['community_id'], actor_id)
        community = _require_community(community_id=req['community_id'])
        if approve:
            active = db.execute(select(User.id).where(User.id == req['user_id'], User.active == 1)).scalar()
            if active is None:
                raise CommunityError('A conta solicitante não está ativa.', 409)
            _ensure_interaction_allowed(actor_id, req['user_id'])
            _ensure_access(req['user_id'], 'join_closed_community', community['minimum_level'])
            _insert_once(CommunityMembership, {'community_id':req['community_id'],
                'user_id':req['user_id'], 'role':'member', 'joined_at':utcnow()},
                ['community_id','user_id'])
        db.execute(update(CommunityJoinRequest).where(CommunityJoinRequest.id == request_id,
            CommunityJoinRequest.status == 'pending').values(status='approved' if approve else 'denied',
                resolved_at=utcnow(), resolved_by=actor_id))
        if approve:
            db.execute(update(CommunityInvite).where(CommunityInvite.community_id == req['community_id'],
                CommunityInvite.invitee_id == req['user_id'], CommunityInvite.status == 'pending').values(
                    status='cancelled', resolved_at=utcnow()))


def invite_member(actor_id, community_id, username):
    if not storable_text(username) or not 3 <= len(username) <= 80:
        raise CommunityError('Informe o username da pessoa que deseja convidar.')
    db = get_db()
    with db:
        _lock_actor(db, actor_id)
        community = _require_community(community_id=community_id)
        _moderator(community_id, actor_id)
        invitee = db.execute(select(User.id).where(func.lower(User.username) == username.strip().lower(),
            User.active == 1)).scalar()
        if invitee is None or invitee == actor_id:
            raise CommunityError('Não encontramos essa conta ativa para convidar.', 404)
        _ensure_interaction_allowed(actor_id, invitee)
        if _active_member(community_id, invitee):
            raise CommunityError('Essa pessoa já participa da comunidade.', 409)
        _insert_once(CommunityInvite, {'community_id': community_id, 'inviter_id': actor_id,
            'invitee_id': invitee, 'status': 'pending', 'created_at': utcnow()}, ['community_id','invitee_id'])
    return invitee


def resolve_invite(user_id, invite_id, accept):
    invite_id = _identifier(invite_id)
    db = get_db()
    with db:
        _lock_actor(db, user_id)
        invite = db.execute(select(CommunityInvite.__table__).where(
            CommunityInvite.id == invite_id, CommunityInvite.invitee_id == user_id,
            CommunityInvite.status == 'pending').with_for_update()).fetchone()
        if invite is None:
            raise CommunityError('Convite não encontrado.', 404)
        community = _require_community(community_id=invite['community_id'])
        if accept:
            _ensure_interaction_allowed(user_id, invite['inviter_id'])
            _ensure_access(user_id, 'join_closed_community', community['minimum_level'])
            _insert_once(CommunityMembership, {'community_id': invite['community_id'], 'user_id': user_id,
                'role': 'member', 'joined_at': utcnow()}, ['community_id','user_id'])
        db.execute(update(CommunityInvite).where(CommunityInvite.id == invite_id).values(
            status='accepted' if accept else 'declined', resolved_at=utcnow()))
        if accept:
            db.execute(update(CommunityJoinRequest).where(
                CommunityJoinRequest.community_id == invite['community_id'],
                CommunityJoinRequest.user_id == user_id,
                CommunityJoinRequest.status == 'pending').values(status='cancelled', resolved_at=utcnow()))


def leave_community(user_id, community_id):
    community_id = _identifier(community_id)
    db = get_db()
    with db:
        _lock_actor(db, user_id)
        member = _active_member(community_id, user_id)
        if member is None:
            raise CommunityError('Você não participa desta comunidade.', 404)
        if member['role'] == 'owner':
            successor = db.execute(select(CommunityMembership.__table__).where(
                CommunityMembership.community_id == community_id,
                CommunityMembership.user_id != user_id).join(User,
                    User.id == CommunityMembership.user_id).where(User.active == 1).order_by(
                    (CommunityMembership.role == 'moderator').desc(),
                    CommunityMembership.joined_at, CommunityMembership.user_id).limit(1)).fetchone()
            if successor:
                db.execute(update(CommunityMembership).where(
                    CommunityMembership.community_id == community_id,
                    CommunityMembership.user_id == successor['user_id']).values(role='owner'))
                db.execute(update(Community).where(Community.id == community_id).values(created_by=successor['user_id']))
            else:
                old_cover = _require_community(community_id=community_id, active=False)['cover']
                db.execute(update(Community).where(Community.id == community_id).values(archived=1,
                    created_by=None, cover=None, updated_at=utcnow()))
                if old_cover:
                    from ..privacy.cleanup import queue_image
                    queue_image('cover', old_cover)
        db.execute(delete(CommunityMembership).where(CommunityMembership.community_id == community_id,
            CommunityMembership.user_id == user_id))
        db.execute(delete(CommunityJoinRequest).where(CommunityJoinRequest.community_id == community_id,
            CommunityJoinRequest.user_id == user_id))


def update_community(actor_id, community_id, fields, cover_filename=None):
    name = fields.get('name', '').strip() if isinstance(fields.get('name'), str) else ''
    description = fields.get('description', '').strip() if isinstance(fields.get('description'), str) else ''
    if not storable_text(name) or not 2 <= len(name) <= 80:
        raise CommunityError('O nome deve ter entre 2 e 80 caracteres.')
    if not storable_text(description) or len(description) > 1000:
        raise CommunityError('A descrição pode ter até 1000 caracteres.')
    mode, theme, icon = fields.get('mode'), fields.get('theme'), fields.get('icon')
    if mode not in ('open','closed') or theme not in THEMES or icon not in ICONS:
        raise CommunityError('Escolha opções válidas de acesso e aparência.')
    try:
        minimum_level = int(fields.get('minimum_level', 1))
    except (TypeError, ValueError):
        raise CommunityError('O nível mínimo precisa ser um número inteiro.') from None
    if not 1 <= minimum_level <= 999:
        raise CommunityError('O nível mínimo deve estar entre 1 e 999.')
    cover_filename = _cover_name(cover_filename)
    db = get_db()
    with db:
        _lock_actor(db, actor_id)
        community = _require_community(community_id=community_id)
        _moderator(community_id, actor_id)
        values = dict(name=name, description=description, mode=mode, minimum_level=minimum_level,
            theme=theme, icon=icon, updated_at=utcnow())
        if cover_filename:
            values['cover'] = cover_filename
        db.execute(update(Community).where(Community.id == community_id).values(**values))
        if cover_filename and community['cover'] and cover_filename != community['cover']:
            from ..privacy.cleanup import queue_image
            queue_image('cover', community['cover'])


def create_post(user_id, community_id, title, body, work_id=None):
    title = title.strip() if storable_text(title) else ''
    body = body.strip() if storable_text(body) else ''
    if not 1 <= len(title) <= 120:
        raise CommunityError('O título deve ter entre 1 e 120 caracteres.')
    if not 1 <= len(body) <= 5000:
        raise CommunityError('A publicação deve ter entre 1 e 5000 caracteres.')
    if work_id in ('', None):
        work_id = None
    else:
        work_id = _identifier(work_id, 'Escolha uma obra válida do catálogo.')
    db = get_db()
    now = utcnow()
    with db:
        _lock_actor(db, user_id)
        community = _require_community(community_id=community_id)
        if not _active_member(community_id, user_id):
            raise CommunityError('Entre na comunidade para publicar.', 403)
        work_query = select(Work.id).where(Work.id == work_id, Work.active == 1)
        if community['category_id'] is not None:
            work_query = work_query.where(Work.categoria_id == community['category_id'])
        if work_id is not None and db.execute(work_query).scalar() is None:
            raise CommunityError('A obra vinculada não está disponível.', 404)
        post_id = db.execute(insert(CommunityPost).values(community_id=community_id, author_id=user_id,
            work_id=work_id, title=title, body=body, created_at=now, updated_at=now).returning(CommunityPost.id)).scalar()
        from ..progression.service import record_action
        record_action(db, user_id, 'activity', now)
    return post_id


def post_detail(post_id, user_id=None):
    post_id = _identifier(post_id)
    db = get_db()
    post = db.execute(select(CommunityPost.__table__, Community.slug.label('community_slug'),
        Community.name.label('community_name'), Community.mode.label('community_mode'),
        Community.category_id.label('community_category_id'),
        User.username, User.nome, User.imagem).join(Community, Community.id == CommunityPost.community_id)
        .join(User, User.id == CommunityPost.author_id).where(
            CommunityPost.id == post_id, Community.archived == 0)).fetchone()
    if post is None:
        raise CommunityError('Publicação não encontrada.', 404)
    member = _active_member(post['community_id'], user_id) if user_id else None
    if post['community_mode'] == 'closed' and member is None:
        raise CommunityError('Entre nesta comunidade para ver as publicações.', 403)
    if user_id is not None and db.execute(select(Block.id).where(or_(and_(Block.user_id == user_id,
        Block.target_id == post['author_id']), and_(Block.target_id == user_id,
        Block.user_id == post['author_id']))).limit(1)).scalar() is not None:
        raise CommunityError('Publicação não encontrada.', 404)
    comments_query = select(CommunityComment.__table__, User.username, User.nome, User.imagem)
    comments_query = comments_query.join(User, User.id == CommunityComment.author_id).where(
        CommunityComment.post_id == post_id)
    if user_id is not None:
        comment_block = exists(select(Block.id).where(or_(and_(Block.user_id == user_id,
            Block.target_id == CommunityComment.author_id), and_(Block.target_id == user_id,
            Block.user_id == CommunityComment.author_id))))
        comments_query = comments_query.where(~comment_block)
    comments = db.execute(comments_query.order_by(CommunityComment.created_at, CommunityComment.id)).fetchall()
    reactions = db.execute(select(CommunityReaction.kind, func.count().label('total')).where(
        CommunityReaction.post_id == post_id).group_by(CommunityReaction.kind)).fetchall()
    mine = []
    if user_id:
        mine = [row['kind'] for row in db.execute(select(CommunityReaction.kind).where(
            CommunityReaction.post_id == post_id, CommunityReaction.user_id == user_id)).fetchall()]
    work = db.execute(select(Work.id, Work.titulo).where(Work.id == post['work_id'])).fetchone() if post['work_id'] else None
    work_query = select(Work.id, Work.titulo).where(Work.active == 1)
    if post['community_category_id'] is not None:
        work_query = work_query.where(Work.categoria_id == post['community_category_id'])
    works = db.execute(work_query.order_by(Work.titulo, Work.id).limit(100)).fetchall()
    return {'post': post, 'comments': comments, 'reactions': {r['kind']:r['total'] for r in reactions},
        'my_reactions': mine, 'membership': member, 'work': work, 'works': works}


def create_comment(user_id, post_id, body):
    body = body.strip() if storable_text(body) else ''
    if not 1 <= len(body) <= 2000:
        raise CommunityError('O comentário deve ter entre 1 e 2000 caracteres.')
    db = get_db()
    now = utcnow()
    with db:
        _lock_actor(db, user_id)
        detail = post_detail(post_id, user_id)
        if not detail['membership']:
            raise CommunityError('Entre na comunidade para participar da discussão.', 403)
        _ensure_interaction_allowed(user_id, detail['post']['author_id'])
        comment_id = db.execute(insert(CommunityComment).values(post_id=post_id,
            author_id=user_id, body=body, created_at=now, updated_at=now).returning(CommunityComment.id)).scalar()
        from ..progression.service import record_action
        record_action(db, user_id, 'activity', now)
    return comment_id


def set_reaction(user_id, post_id, kind, enabled):
    if kind not in REACTIONS or type(enabled) is not bool:
        raise CommunityError('Reação inválida.')
    db = get_db()
    with db:
        _lock_actor(db, user_id)
        detail = post_detail(post_id, user_id)
        if not detail['membership']:
            raise CommunityError('Entre na comunidade para reagir.', 403)
        _ensure_interaction_allowed(user_id, detail['post']['author_id'])
        if enabled:
            _insert_once(CommunityReaction, {'user_id':user_id, 'post_id':post_id,
                'kind':kind, 'created_at':utcnow()}, ['user_id','post_id','kind'])
        else:
            db.execute(delete(CommunityReaction).where(CommunityReaction.user_id == user_id,
                CommunityReaction.post_id == post_id, CommunityReaction.kind == kind))
    return post_detail(post_id, user_id)['reactions']


def delete_post(user_id, post_id):
    post_id = _identifier(post_id)
    db = get_db()
    with db:
        _lock_actor(db, user_id)
        post = db.execute(select(CommunityPost.__table__).where(CommunityPost.id == post_id)).fetchone()
        if post is None:
            raise CommunityError('Publicação não encontrada.', 404)
        community = _require_community(community_id=post['community_id'])
        member = _active_member(post['community_id'], user_id)
        if community['mode'] == 'closed' and member is None:
            raise CommunityError('Entre na comunidade para moderar esta publicação.', 403)
        if post['author_id'] != user_id and (not member or member['role'] not in ('owner','moderator')):
            raise CommunityError('Você não pode excluir esta publicação.', 403)
        db.execute(delete(CommunityPost).where(CommunityPost.id == post_id))
    return post['community_id']


def edit_post(user_id, post_id, title, body, work_id=None):
    post_id = _identifier(post_id)
    title = title.strip() if storable_text(title) else ''
    body = body.strip() if storable_text(body) else ''
    if not 1 <= len(title) <= 120 or not 1 <= len(body) <= 5000:
        raise CommunityError('O título deve ter até 120 caracteres e a publicação até 5000.')
    if work_id in ('', None):
        work_id = None
    else:
        work_id = _identifier(work_id, 'Escolha uma obra válida do catálogo.')
    db = get_db()
    with db:
        _lock_actor(db, user_id)
        post = db.execute(select(CommunityPost.__table__).where(CommunityPost.id == post_id)).fetchone()
        if post is None:
            raise CommunityError('Publicação não encontrada.', 404)
        if post['author_id'] != user_id:
            raise CommunityError('Somente a pessoa autora pode editar esta publicação.', 403)
        community = _require_community(community_id=post['community_id'])
        if not _active_member(post['community_id'], user_id):
            raise CommunityError('Entre na comunidade para editar a publicação.', 403)
        work_query = select(Work.id).where(Work.id == work_id, Work.active == 1)
        if community['category_id'] is not None:
            work_query = work_query.where(Work.categoria_id == community['category_id'])
        if work_id is not None and db.execute(work_query).scalar() is None:
            raise CommunityError('A obra vinculada não está disponível.', 404)
        db.execute(update(CommunityPost).where(CommunityPost.id == post_id).values(
            title=title, body=body, work_id=work_id, updated_at=utcnow()))


def edit_comment(user_id, comment_id, body):
    comment_id = _identifier(comment_id)
    body = body.strip() if storable_text(body) else ''
    if not 1 <= len(body) <= 2000:
        raise CommunityError('O comentário deve ter entre 1 e 2000 caracteres.')
    db = get_db()
    with db:
        _lock_actor(db, user_id)
        comment = db.execute(select(CommunityComment.__table__).where(CommunityComment.id == comment_id)).fetchone()
        if comment is None:
            raise CommunityError('Comentário não encontrado.', 404)
        if comment['author_id'] != user_id:
            raise CommunityError('Somente a pessoa autora pode editar este comentário.', 403)
        detail = post_detail(comment['post_id'], user_id)
        if not detail['membership']:
            raise CommunityError('Entre na comunidade para editar o comentário.', 403)
        db.execute(update(CommunityComment).where(CommunityComment.id == comment_id).values(
            body=body, updated_at=utcnow()))
    return comment['post_id']


def delete_comment(user_id, comment_id):
    comment_id = _identifier(comment_id)
    db = get_db()
    with db:
        _lock_actor(db, user_id)
        comment = db.execute(select(CommunityComment.__table__).where(CommunityComment.id == comment_id)).fetchone()
        if comment is None:
            raise CommunityError('Comentário não encontrado.', 404)
        post = db.execute(select(CommunityPost.__table__).where(CommunityPost.id == comment['post_id'])).fetchone()
        if post is None:
            raise CommunityError('Publicação não encontrada.', 404)
        community = _require_community(community_id=post['community_id'])
        member = _active_member(post['community_id'], user_id)
        if community['mode'] == 'closed' and member is None:
            raise CommunityError('Entre na comunidade para moderar este comentário.', 403)
        if comment['author_id'] != user_id and (not member or member['role'] not in ('owner','moderator')):
            raise CommunityError('Você não pode excluir este comentário.', 403)
        db.execute(delete(CommunityComment).where(CommunityComment.id == comment_id))
    return comment['post_id']


def set_member_role(actor_id, community_id, member_id, role):
    member_id = _identifier(member_id)
    if role not in ('moderator','member'):
        raise CommunityError('Papel de membro inválido.')
    db = get_db()
    with db:
        _lock_actor(db, actor_id)
        actor = _moderator(community_id, actor_id)
        if actor['role'] != 'owner':
            raise CommunityError('Somente a pessoa responsável pode alterar moderadores.', 403)
        target = _active_member(community_id, member_id)
        if target is None or target['role'] == 'owner' or member_id == actor_id:
            raise CommunityError('Membro não encontrado ou não pode ser alterado.', 404)
        db.execute(update(CommunityMembership).where(CommunityMembership.community_id == community_id,
            CommunityMembership.user_id == member_id).values(role=role))


def remove_member(actor_id, community_id, member_id):
    member_id = _identifier(member_id)
    db = get_db()
    with db:
        _lock_actor(db, actor_id)
        actor = _moderator(community_id, actor_id)
        target = _active_member(community_id, member_id)
        if target is None or target['role'] == 'owner' or member_id == actor_id:
            raise CommunityError('Membro não encontrado ou não pode ser removido.', 404)
        if target['role'] == 'moderator' and actor['role'] != 'owner':
            raise CommunityError('Somente a pessoa responsável pode remover moderadores.', 403)
        db.execute(delete(CommunityMembership).where(CommunityMembership.community_id == community_id,
            CommunityMembership.user_id == member_id))
        db.execute(delete(CommunityInvite).where(CommunityInvite.community_id == community_id,
            CommunityInvite.invitee_id == member_id, CommunityInvite.status == 'pending'))
        db.execute(update(CommunityJoinRequest).where(CommunityJoinRequest.community_id == community_id,
            CommunityJoinRequest.user_id == member_id, CommunityJoinRequest.status == 'pending').values(
                status='cancelled', resolved_at=utcnow()))
