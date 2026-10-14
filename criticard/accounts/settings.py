"""Session-owned account actions and private blocked-person management."""
import json
from datetime import date, datetime

from flask import Blueprint, Response, flash, g, jsonify, redirect, request, session, url_for
from sqlalchemy import func, or_, select, update
from werkzeug.security import check_password_hash, generate_password_hash

from criticard.db import get_db
from criticard.form_security import attempt_budget
from criticard.models import Card, User, utcnow
from criticard.security import login_required, session_identity, valid_session_identity, wants_json
from criticard.social import service as social
from criticard.social.models import Block, Follow, Friend
from criticard.storage import image_url
from criticard.validation import senha_forte, storable_text
from .service import invalidate_email_links

bp = Blueprint('account_settings', __name__)
PAGE_SIZE = 24


class AccountSettingsError(ValueError):
    def __init__(self, message, field=None, status=422, retry=0):
        super().__init__(message)
        self.field = field
        self.status = status
        self.retry = retry


def _payload():
    data = request.get_json(silent=True) if request.is_json else request.form
    return data if hasattr(data, 'get') else {}


def _query(value):
    return value.strip() if storable_text(value) and len(value) <= 200 else ''


def _page(value):
    if type(value) is int:
        return max(1, value)
    if isinstance(value, str) and len(value) <= 7 and value.isdecimal():
        return max(1, int(value))
    return 1


def blocked_users(user_id, query='', page=1):
    """List only blocks made by this owner, exposing public profile fields."""
    query = _query(query)
    db = get_db()
    conditions = [Block.user_id == user_id]
    if query:
        term = query[1:] if query.startswith('@') and len(query) > 1 else query
        pattern = '%' + term.casefold().replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
        normalize = func.casefold if db.dialect == 'sqlite' else func.lower
        conditions.append(or_(*(normalize(field).like(pattern, escape='\\')
            for field in (User.username, User.nome, User.apelido))))
    source = User.__table__.join(Block.__table__, Block.target_id == User.id)
    total = db.execute(select(func.count()).select_from(source).where(*conditions)).scalar()
    pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = min(_page(page), pages)
    records = db.execute(select(User.id, User.username, User.nome, User.apelido, User.about, User.imagem)
        .select_from(source).where(*conditions).order_by(func.lower(User.nome), User.id)
        .limit(PAGE_SIZE).offset((page - 1) * PAGE_SIZE)).fetchall()
    people = [dict(row, avatar_url=image_url('avatar', row['imagem'])) for row in records]
    return {'people': people, 'total': total, 'page': page, 'pages': pages, 'query': query}


def _return_url(section, payload=None):
    arguments = {'secao': section}
    if section == 'bloqueados':
        payload = payload or {}
        data = blocked_users(g.user['id'], _query(payload.get('q', '')), _page(payload.get('page', 1)))
        if data['query']:
            arguments['q'] = data['query']
        if data['page'] > 1:
            arguments['page'] = data['page']
    return url_for('settings.index', **arguments)


@bp.after_request
def private_response(response):
    response.headers['Cache-Control'] = 'no-store'
    response.headers['Referrer-Policy'] = 'no-referrer'
    return response


@bp.errorhandler(AccountSettingsError)
def account_error(error):
    if wants_json():
        response = jsonify(error=str(error), field=error.field)
        response.status_code = error.status
    else:
        action = {
            'account_settings.change_password': 'change_password',
            'account_settings.revoke_sessions': 'revoke_sessions',
        }.get(request.endpoint)
        if action is not None:
            session['_settings_account_error'] = {
                'field': error.field, 'message': str(error), 'action': action,
            }
        flash(str(error), 'error')
        response = redirect(_return_url('conta'))
    if error.retry:
        response.headers['Retry-After'] = str(error.retry)
    return response


def _security_input():
    retry = attempt_budget('settings_security')
    if retry:
        raise AccountSettingsError('Muitas tentativas. Aguarde alguns minutos e tente novamente.',
            status=429, retry=retry)
    payload = _payload()
    current = payload.get('current_password', '')
    if not storable_text(current) or not 1 <= len(current) <= 1024:
        raise AccountSettingsError('Informe sua senha atual.', 'current_password')
    return payload, current


def _locked_account(current_password):
    """Recheck identity and current credentials after acquiring the account lock."""
    user = get_db().execute(update(User).where(User.id == g.user['id'], User.active == 1)
        .values(session_version=User.session_version).returning(*User.__table__.columns)).fetchone()
    if not valid_session_identity(user, session):
        raise AccountSettingsError('Sua sessão expirou. Entre novamente.', status=401)
    if not check_password_hash(user['senha'], current_password):
        raise AccountSettingsError('A senha atual está incorreta.', 'current_password', status=403)
    return user


@bp.post('/configuracoes/conta/senha')
@login_required
def change_password():
    payload, current = _security_input()
    password = payload.get('new_password', '')
    if not senha_forte(password):
        raise AccountSettingsError('Use 8 a 128 caracteres, com maiúscula, minúscula, número e !@#$%&_*.', 'new_password')
    if payload.get('confirm_password') != password:
        raise AccountSettingsError('As senhas precisam ser iguais.', 'confirm_password')
    password_hash = generate_password_hash(password)
    db = get_db()
    with db:
        user = _locked_account(current)
        changed = db.execute(update(User).where(User.id == user['id'])
            .values(senha=password_hash, session_version=User.session_version + 1)
            .returning(User.session_version)).scalar()
        invalidate_email_links(user['id'])
    # Only refresh the identity from the credentials this action wrote. A
    # concurrent reset/revocation must not grant a session for newer credentials.
    fresh = db.execute(select(User).where(User.id == user['id'], User.active == 1,
        User.session_version == changed, User.senha == password_hash)).fetchone()
    if fresh is None:
        session.clear()
        raise AccountSettingsError('Senha alterada. Entre novamente para continuar.', status=401)
    session['session_version'] = fresh['session_version']
    session['auth_stamp'] = session_identity(fresh)
    session.pop('_settings_account_error', None)
    message = 'Senha alterada. As outras sessões e os links antigos foram encerrados.'
    if wants_json():
        return jsonify(message=message)
    flash(message, 'success')
    return redirect(_return_url('conta'))


@bp.post('/configuracoes/conta/sessoes')
@login_required
def revoke_sessions():
    _, current = _security_input()
    db = get_db()
    with db:
        user = _locked_account(current)
        db.execute(update(User).where(User.id == user['id']).values(session_version=User.session_version + 1))
        invalidate_email_links(user['id'])
    session.clear()
    message = 'Todas as sessões foram encerradas. Entre novamente para continuar.'
    if wants_json():
        return jsonify(message=message, redirect=url_for('auth.index'))
    flash(message, 'success')
    return redirect(url_for('auth.index'))


def _records(model, fields, condition):
    return get_db().execute(select(*(getattr(model, name) for name in fields))
        .where(condition).order_by(model.id)).fetchall()


def _json_value(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    raise TypeError('Unsupported export value')


@bp.get('/configuracoes/conta/exportar')
@login_required
def export_data():
    from criticard.backlog.models import BacklogItem
    from criticard.chat.models import Message
    from criticard.chat.models import ConversationMember, GroupChat, GroupInvite, GroupJoinRequest
    from criticard.communities.models import (Community, CommunityComment, CommunityInvite,
        CommunityJoinRequest, CommunityMembership, CommunityPost, CommunityReaction)
    from criticard.settings.service import get_preferences
    from criticard.models import Contact
    from criticard.social.models import (CardLike, CategoryFollow, Comment, Notification, Report,
        WorkFollow)
    from criticard.privacy.service import export_requests
    from criticard.progression.models import ProgressionProfile, ExperienceEvent, AchievementGrant, RewardGrant
    owner_id = g.user['id']
    data = {
        'exported_at': utcnow(),
        'profile': {name: g.user[name] for name in ('id', 'username', 'nome', 'apelido', 'about',
            'imagem', 'email', 'email_verified', 'created_at')},
        'preferences': get_preferences(owner_id),
        'cards': _records(Card, ('id', 'titulo', 'capa', 'sobre', 'nota', 'obra_id', 'archived', 'created_at', 'updated_at'), Card.author_id == owner_id),
        'backlog': _records(BacklogItem, ('id', 'work_id', 'status', 'progress', 'progress_unit', 'visibility', 'created_at', 'updated_at'), BacklogItem.user_id == owner_id),
        'follows': _records(Follow, ('id', 'target_id', 'created_at'), Follow.user_id == owner_id),
        'work_follows': _records(WorkFollow, ('id', 'work_id', 'created_at'), WorkFollow.user_id == owner_id),
        'category_follows': _records(CategoryFollow, ('id', 'category_id', 'created_at'), CategoryFollow.user_id == owner_id),
        'followers': _records(Follow, ('id', 'user_id', 'created_at'), Follow.target_id == owner_id),
        'friends': _records(Friend, ('id', 'user_low_id', 'user_high_id', 'requested_by', 'status', 'created_at', 'accepted_at'),
            or_(Friend.user_low_id == owner_id, Friend.user_high_id == owner_id)),
        'messages': _records(Message, ('id', 'conversation_id', 'body', 'created_at'), Message.sender_id == owner_id),
        'chat_groups': {
            'created_or_owned': get_db().execute(select(GroupChat.__table__).where(
                or_(GroupChat.creator_id==owner_id,GroupChat.owner_id==owner_id)).order_by(
                GroupChat.created_at,GroupChat.conversation_id)).fetchall(),
            'memberships': get_db().execute(select(ConversationMember.conversation_id,
                ConversationMember.role,ConversationMember.joined_at).join(GroupChat,
                GroupChat.conversation_id==ConversationMember.conversation_id).where(
                ConversationMember.user_id==owner_id).order_by(ConversationMember.joined_at)).fetchall(),
            'invites_sent': get_db().execute(select(GroupInvite.__table__).where(
                GroupInvite.inviter_id==owner_id).order_by(GroupInvite.created_at)).fetchall(),
            'invites_received': get_db().execute(select(GroupInvite.__table__).where(
                GroupInvite.invitee_id==owner_id).order_by(GroupInvite.created_at)).fetchall(),
            'join_requests': get_db().execute(select(GroupJoinRequest.__table__).where(
                GroupJoinRequest.user_id==owner_id).order_by(GroupJoinRequest.created_at)).fetchall(),
        },
        'communities': {
            'created_or_owned': get_db().execute(select(Community.__table__).where(
                or_(Community.created_by == owner_id,
                    Community.id.in_(select(CommunityMembership.community_id).where(
                        CommunityMembership.user_id == owner_id, CommunityMembership.role == 'owner'))))
                .order_by(Community.created_at, Community.id)).fetchall(),
            'memberships': get_db().execute(select(CommunityMembership.__table__).where(
                CommunityMembership.user_id == owner_id).order_by(
                    CommunityMembership.joined_at, CommunityMembership.community_id)).fetchall(),
            'posts': _records(CommunityPost, ('id','community_id','work_id','title','body','created_at','updated_at'),
                CommunityPost.author_id == owner_id),
            'comments': _records(CommunityComment, ('id','post_id','body','created_at','updated_at'),
                CommunityComment.author_id == owner_id),
            'reactions': _records(CommunityReaction, ('id','post_id','kind','created_at'),
                CommunityReaction.user_id == owner_id),
            'join_requests': get_db().execute(select(CommunityJoinRequest.__table__).where(
                CommunityJoinRequest.user_id == owner_id).order_by(CommunityJoinRequest.created_at)).fetchall(),
            'invites_sent': get_db().execute(select(CommunityInvite.__table__).where(
                CommunityInvite.inviter_id == owner_id).order_by(CommunityInvite.created_at)).fetchall(),
            'invites_received': get_db().execute(select(CommunityInvite.__table__).where(
                CommunityInvite.invitee_id == owner_id).order_by(CommunityInvite.created_at)).fetchall(),
        },
        'comments': _records(Comment, ('id', 'card_id', 'body', 'created_at', 'updated_at'), Comment.author_id == owner_id),
        'likes': _records(CardLike, ('id', 'card_id', 'created_at'), CardLike.user_id == owner_id),
        'blocks': _records(Block, ('id', 'target_id', 'created_at'), Block.user_id == owner_id),
        'notifications': _records(Notification, ('id', 'actor_id', 'kind', 'card_id', 'comment_id', 'created_at', 'read_at'),
            Notification.recipient_id == owner_id),
        'reports': _records(Report, ('id', 'target_type', 'target_id', 'reason', 'status', 'created_at', 'resolved_at'),
            Report.reporter_id == owner_id),
        'contacts': _records(Contact, ('id', 'nome', 'email', 'mensagem'), Contact.user_id == owner_id),
        'privacy_requests': export_requests(owner_id),
        'progression': {
            'profile': get_db().execute(select(ProgressionProfile).where(ProgressionProfile.user_id==owner_id)).fetchone(),
            'events': get_db().execute(select(ExperienceEvent).where(ExperienceEvent.user_id==owner_id).order_by(ExperienceEvent.id)).fetchall(),
            'achievements': get_db().execute(select(AchievementGrant).where(AchievementGrant.user_id==owner_id).order_by(AchievementGrant.slug)).fetchall(),
            'rewards': get_db().execute(select(RewardGrant).where(RewardGrant.user_id==owner_id).order_by(RewardGrant.slug)).fetchall(),
        },
    }
    response = Response(json.dumps(data, ensure_ascii=False, default=_json_value), content_type='application/json; charset=utf-8')
    response.headers['Content-Disposition'] = f'attachment; filename="criticard-dados-{owner_id}.json"'
    return response


@bp.post('/configuracoes/bloqueados/<int:user_id>/desbloquear')
@login_required
def unblock(user_id):
    payload = _payload()
    try:
        social.set_block(g.user['id'], user_id, False)
    except social.SocialError as error:
        if wants_json():
            return jsonify(error=str(error)), error.status
        flash(str(error), 'error')
        return redirect(_return_url('bloqueados', payload))
    message = 'Pessoa desbloqueada.'
    if wants_json():
        return jsonify(message=message)
    flash(message, 'success')
    return redirect(_return_url('bloqueados', payload))
