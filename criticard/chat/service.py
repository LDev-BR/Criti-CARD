"""Authorization and transactional persistence shared by HTTP and Socket.IO."""
import re
import secrets
import unicodedata
from time import time
from uuid import UUID
from datetime import timezone

from flask import current_app
from sqlalchemy import and_, delete, func, insert, or_, select, update
from sqlalchemy.exc import IntegrityError

from criticard.db import get_db
from criticard.models import User, utcnow
from criticard.social.models import Block
from criticard.social.service import users_blocked
from criticard.storage import image_url
from criticard.validation import storable_text
from criticard.progression.access import evaluate_social_access
from criticard.progression.service import lock_owner, require_owner_session
from criticard.progression.types import ProgressionError
from .models import (ChatRateAttempt, Conversation, ConversationMember, GroupChat,
    GroupInvite, GroupJoinRequest, Message)


class ChatError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


GROUP_VISUALS = frozenset(('gold','ocean','violet','emerald','ruby'))


def _group_slug(name):
    value = unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode('ascii').lower()
    value = re.sub(r'[^a-z0-9]+', '-', value).strip('-') or 'grupo'
    return f'{value[:68]}-{secrets.token_hex(3)}'


def _require_group(db, conversation_id, *, include_archived=False):
    conversation_id = identifier(conversation_id, 'Grupo')
    conditions = [GroupChat.conversation_id == conversation_id, Conversation.kind == 'group']
    if not include_archived:
        conditions.append(GroupChat.archived == 0)
    row = db.execute(select(GroupChat.__table__).join(Conversation,
        Conversation.id == GroupChat.conversation_id).where(*conditions)).fetchone()
    if row is None:
        raise ChatError('Grupo não encontrado.', 404)
    return row


def _require_group_role(db, actor_id, conversation_id, roles=('owner','moderator')):
    _lock_chat_user(db,actor_id,session_actor=True)
    group = _require_group(db, conversation_id)
    db.execute(update(GroupChat).where(GroupChat.conversation_id==conversation_id)
        .values(updated_at=GroupChat.updated_at))
    group = _require_group(db,conversation_id)
    member = db.execute(select(ConversationMember.__table__).where(
        ConversationMember.conversation_id == conversation_id,
        ConversationMember.user_id == actor_id)).fetchone()
    if member is None or member['role'] not in roles or group['owner_id'] != actor_id and member['role'] == 'owner':
        raise ChatError('Esta ação é reservada à moderação do grupo.', 403)
    return group, member


def _require_group_access(user_id, action, minimum_level):
    decision = evaluate_social_access(get_db(), user_id, action, utcnow(), minimum_level=minimum_level)
    if decision.eligible:
        return decision
    if decision.reason == 'no_contribution':
        message = 'Faça uma contribuição válida antes de entrar em chats em grupo.'
    elif decision.reason == 'time':
        message = f'Aguarde mais {decision.hours_remaining:g} horas desde sua primeira contribuição.'
    elif decision.reason in ('xp','level'):
        message = f'Este grupo exige nível {decision.required_level} e {decision.required_xp} XP.'
    else:
        message = f'Complete três dias diferentes com a cota de {200} XP para liberar esta ação.'
    raise ChatError(message, 403)


def _lock_chat_user(db,user_id,*,session_actor=False):
    try:
        owner = lock_owner(db,user_id)
        if session_actor:
            require_owner_session(owner)
        return owner
    except ProgressionError as error:
        raise ChatError(str(error),error.status) from None


def _active_user(user_id):
    if get_db().execute(select(User.id).where(User.id==user_id,User.active==1)).scalar() is None:
        raise ChatError('Pessoa não encontrada.',404)


def _group_member_conflicts(db, conversation_id, user_id):
    member_ids = db.execute(select(ConversationMember.user_id).join(User,
        User.id == ConversationMember.user_id).where(
        ConversationMember.conversation_id == conversation_id,
        ConversationMember.user_id != user_id, User.active == 1)).fetchall()
    if any(users_blocked(user_id, row['user_id']) for row in member_ids):
        raise ChatError('Não é possível entrar em um grupo com uma pessoa bloqueada.', 403)


def _add_group_member(db, conversation_id, user_id, now=None):
    existing = db.execute(select(ConversationMember.__table__).where(
        ConversationMember.conversation_id == conversation_id,
        ConversationMember.user_id == user_id)).fetchone()
    if existing:
        return existing
    db.execute(insert(ConversationMember).values(conversation_id=conversation_id,
        user_id=user_id, role='member', joined_at=now or utcnow()))
    return db.execute(select(ConversationMember.__table__).where(
        ConversationMember.conversation_id == conversation_id,
        ConversationMember.user_id == user_id)).fetchone()


def _clear_pending_access(db, conversation_id, user_id, *, keep_request_id=None, keep_invite_id=None):
    now = utcnow()
    request_update = update(GroupJoinRequest).where(GroupJoinRequest.conversation_id==conversation_id,
        GroupJoinRequest.user_id==user_id,GroupJoinRequest.status=='pending')
    invite_update = update(GroupInvite).where(GroupInvite.conversation_id==conversation_id,
        GroupInvite.invitee_id==user_id,GroupInvite.status=='pending')
    if keep_request_id is not None:
        request_update = request_update.where(GroupJoinRequest.id!=keep_request_id)
    if keep_invite_id is not None:
        invite_update = invite_update.where(GroupInvite.id!=keep_invite_id)
    db.execute(request_update.values(status='cancelled',resolved_at=now))
    db.execute(invite_update.values(status='cancelled',resolved_at=now))


def create_group_chat(user_id, name, description='', mode='open', minimum_level=1, visual_token='gold'):
    if not storable_text(name) or not 3 <= len(name.strip()) <= 60:
        raise ChatError('O nome do grupo deve ter entre 3 e 60 caracteres.')
    if not storable_text(description or '') or len((description or '').strip()) > 500:
        raise ChatError('A descrição pode ter até 500 caracteres.')
    if mode not in ('open','closed'):
        raise ChatError('Escolha um modo de entrada válido.')
    try:
        minimum_level = identifier(minimum_level, 'Nível mínimo')
    except ChatError:
        raise ChatError('O nível mínimo deve ser um inteiro positivo.') from None
    if minimum_level > 999:
        raise ChatError('O nível mínimo não pode ultrapassar 999.')
    if not isinstance(visual_token,str) or visual_token not in GROUP_VISUALS:
        raise ChatError('Escolha uma identidade visual disponível.')
    db = get_db()
    now = utcnow()
    with db:
        _lock_chat_user(db,user_id,session_actor=True)
        _require_group_access(user_id, 'create_group_chat', 1)
        conversation_id = db.execute(insert(Conversation).values(
            kind='group', pair_low_id=None, pair_high_id=None, created_at=now
        ).returning(Conversation.id)).scalar()
        db.execute(insert(GroupChat).values(conversation_id=conversation_id,
            owner_id=user_id, creator_id=user_id, name=name.strip(), slug=_group_slug(name.strip()),
            description=(description or '').strip(), mode=mode, minimum_level=minimum_level,
            visual_token=visual_token, created_at=now, updated_at=now))
        db.execute(insert(ConversationMember).values(conversation_id=conversation_id,
            user_id=user_id, role='owner', joined_at=now))
    return conversation_summary(user_id, conversation_id)


def _group_preview(row, user_id, joined, request_pending=False, invite_id=None):
    required_action = 'join_open_chat' if row['mode'] == 'open' else 'join_closed_chat'
    decision = evaluate_social_access(get_db(), user_id, required_action, utcnow(),
        minimum_level=row['minimum_level'])
    return {'id': row['conversation_id'], 'name': row['name'], 'slug': row['slug'],
        'description': row['description'] if row['mode']=='open' else '', 'mode': row['mode'],
        'minimum_level': row['minimum_level'], 'visual_token': row['visual_token'],
        'created_at': row['created_at'], 'joined': joined, 'request_pending': request_pending,
        'invite_id': invite_id, 'can_join': decision.eligible,
        'access_reason': decision.reason, 'required_level': decision.required_level,
        'required_xp': decision.required_xp, 'hours_remaining': decision.hours_remaining,
        'full_cap_days': decision.full_cap_days,
        'member_count': None if row['mode'] == 'closed' else row['member_count']}


def discover_group_chats(user_id, search=''):
    db = get_db()
    statement = select(GroupChat.__table__,
        func.count(User.id).label('member_count')).join(
            Conversation, Conversation.id == GroupChat.conversation_id).outerjoin(
            ConversationMember, ConversationMember.conversation_id == GroupChat.conversation_id).outerjoin(
            User, and_(User.id==ConversationMember.user_id,User.active==1)).where(
            GroupChat.archived == 0, Conversation.kind == 'group').group_by(GroupChat.conversation_id)
    if search and storable_text(search):
        statement = statement.where(GroupChat.name.ilike(f'%{search.strip()[:60]}%'))
    rows = db.execute(statement.order_by(GroupChat.created_at.desc()).limit(100)).fetchall()
    memberships = {row['conversation_id'] for row in db.execute(select(ConversationMember.conversation_id).where(
        ConversationMember.user_id == user_id)).fetchall()}
    requests = {row['conversation_id'] for row in db.execute(select(GroupJoinRequest.conversation_id).where(
        GroupJoinRequest.user_id == user_id, GroupJoinRequest.status == 'pending')).fetchall()}
    invites = {row['conversation_id']: row['id'] for row in db.execute(select(GroupInvite.id,
        GroupInvite.conversation_id).where(GroupInvite.invitee_id == user_id,
            GroupInvite.status == 'pending')).fetchall()}
    items = [_group_preview(row,user_id,row['conversation_id'] in memberships,
        row['conversation_id'] in requests,invites.get(row['conversation_id'])) for row in rows]
    return {'groups': items, 'invites': [item for item in items if item['invite_id']]}


def join_open_group(user_id, conversation_id):
    conversation_id = identifier(conversation_id, 'Grupo')
    db = get_db()
    with db:
        _lock_chat_user(db,user_id,session_actor=True)
        db.execute(update(GroupChat).where(GroupChat.conversation_id == conversation_id)
            .values(updated_at=GroupChat.updated_at))
        group = _require_group(db, conversation_id)
        if group['mode'] != 'open':
            raise ChatError('Este grupo fechado exige convite ou aprovação.', 403)
        existing = db.execute(select(ConversationMember.__table__).where(
            ConversationMember.conversation_id == conversation_id,
            ConversationMember.user_id == user_id)).fetchone()
        if existing:
            return existing
        _require_group_access(user_id,'join_open_chat',group['minimum_level'])
        _group_member_conflicts(db,conversation_id,user_id)
        member = _add_group_member(db,conversation_id,user_id)
        _clear_pending_access(db,conversation_id,user_id)
        return member


def request_closed_group_access(user_id, conversation_id):
    conversation_id = identifier(conversation_id, 'Grupo')
    db = get_db()
    now = utcnow()
    with db:
        _lock_chat_user(db,user_id,session_actor=True)
        db.execute(update(GroupChat).where(GroupChat.conversation_id == conversation_id)
            .values(updated_at=GroupChat.updated_at))
        group = _require_group(db,conversation_id)
        if group['mode'] != 'closed':
            raise ChatError('Este grupo está aberto e aceita entrada direta.')
        _require_group_access(user_id,'join_closed_chat',group['minimum_level'])
        if db.execute(select(ConversationMember.conversation_id).where(
                ConversationMember.conversation_id == conversation_id,
                ConversationMember.user_id == user_id)).scalar():
            raise ChatError('Você já participa deste grupo.',409)
        _group_member_conflicts(db,conversation_id,user_id)
        existing = db.execute(select(GroupJoinRequest.__table__).where(
            GroupJoinRequest.conversation_id == conversation_id,
            GroupJoinRequest.user_id == user_id, GroupJoinRequest.status == 'pending')).fetchone()
        if existing:
            return existing
        identity = db.execute(insert(GroupJoinRequest).values(conversation_id=conversation_id,
            user_id=user_id,status='pending',created_at=now).returning(GroupJoinRequest.id)).scalar()
        return db.execute(select(GroupJoinRequest.__table__).where(GroupJoinRequest.id == identity)).fetchone()


def approve_group_request(actor_id, request_id, approve):
    request_id = identifier(request_id,'Solicitação')
    if type(approve) is not bool:
        raise ChatError('Escolha se deseja aprovar a solicitação.')
    db = get_db()
    now = utcnow()
    with db:
        request_row = db.execute(select(GroupJoinRequest.__table__).where(
            GroupJoinRequest.id==request_id,GroupJoinRequest.status=='pending')).fetchone()
        if request_row is None:
            raise ChatError('Solicitação não encontrada.',404)
        _lock_people(actor_id,request_row['user_id'])
        _lock_chat_user(db,actor_id,session_actor=True)
        group, _ = _require_group_role(db,actor_id,request_row['conversation_id'])
        request_row = db.execute(select(GroupJoinRequest.__table__).where(
            GroupJoinRequest.id==request_id,GroupJoinRequest.status=='pending')).fetchone()
        if request_row is None:
            raise ChatError('Solicitação não encontrada.',404)
        if not approve:
            db.execute(update(GroupJoinRequest).where(GroupJoinRequest.id==request_id,
                GroupJoinRequest.status=='pending').values(status='denied',resolved_at=now,resolved_by=actor_id))
            return None
        _lock_chat_user(db,request_row['user_id'])
        _require_group_access(request_row['user_id'],'join_closed_chat',group['minimum_level'])
        _group_member_conflicts(db,request_row['conversation_id'],request_row['user_id'])
        member = _add_group_member(db,request_row['conversation_id'],request_row['user_id'],now)
        db.execute(update(GroupJoinRequest).where(GroupJoinRequest.id==request_id,
            GroupJoinRequest.status=='pending').values(status='approved',resolved_at=now,resolved_by=actor_id))
        _clear_pending_access(db,request_row['conversation_id'],request_row['user_id'],
            keep_request_id=request_id)
        return member


def invite_group_member(actor_id, conversation_id, target_id):
    conversation_id = identifier(conversation_id,'Grupo')
    target_id = identifier(target_id,'Pessoa')
    if actor_id == target_id:
        raise ChatError('Você já participa deste grupo.')
    db = get_db()
    now = utcnow()
    with db:
        group, _ = _require_group_role(db,actor_id,conversation_id)
        _active_user(target_id)
        if db.execute(select(ConversationMember.user_id).where(
                ConversationMember.conversation_id==conversation_id,
                ConversationMember.user_id==target_id)).scalar():
            raise ChatError('Esta pessoa já participa do grupo.',409)
        if users_blocked(actor_id,target_id):
            raise ChatError('Não é possível convidar uma pessoa bloqueada.',403)
        _group_member_conflicts(db,conversation_id,target_id)
        existing = db.execute(select(GroupInvite.__table__).where(
            GroupInvite.conversation_id==conversation_id,GroupInvite.invitee_id==target_id,
            GroupInvite.status=='pending')).fetchone()
        if existing:
            return existing
        identity = db.execute(insert(GroupInvite).values(conversation_id=conversation_id,
            inviter_id=actor_id,invitee_id=target_id,status='pending',created_at=now)
            .returning(GroupInvite.id)).scalar()
        return db.execute(select(GroupInvite.__table__).where(GroupInvite.id==identity)).fetchone()


def accept_group_invite(user_id, invite_id):
    invite_id = identifier(invite_id,'Convite')
    db = get_db()
    now = utcnow()
    with db:
        _lock_chat_user(db,user_id,session_actor=True)
        invite = db.execute(select(GroupInvite.__table__).where(
            GroupInvite.id==invite_id,GroupInvite.invitee_id==user_id,
            GroupInvite.status=='pending')).fetchone()
        if invite is None:
            raise ChatError('Convite não encontrado.',404)
        db.execute(update(GroupChat).where(GroupChat.conversation_id==invite['conversation_id'])
            .values(updated_at=GroupChat.updated_at))
        invite = db.execute(select(GroupInvite.__table__).where(
            GroupInvite.id==invite_id,GroupInvite.invitee_id==user_id,
            GroupInvite.status=='pending')).fetchone()
        if invite is None:
            raise ChatError('Convite não encontrado.',404)
        group = _require_group(db,invite['conversation_id'])
        action = 'join_open_chat' if group['mode']=='open' else 'join_closed_chat'
        _require_group_access(user_id,action,group['minimum_level'])
        _group_member_conflicts(db,invite['conversation_id'],user_id)
        member = _add_group_member(db,invite['conversation_id'],user_id,now)
        db.execute(update(GroupInvite).where(GroupInvite.id==invite_id,GroupInvite.status=='pending')
            .values(status='accepted',resolved_at=now))
        _clear_pending_access(db,invite['conversation_id'],user_id,keep_invite_id=invite_id)
        return member


def decline_group_invite(user_id, invite_id):
    invite_id = identifier(invite_id,'Convite')
    db = get_db()
    with db:
        _lock_chat_user(db,user_id,session_actor=True)
        result = db.execute(update(GroupInvite).where(GroupInvite.id==invite_id,
            GroupInvite.invitee_id==user_id,GroupInvite.status=='pending')
            .values(status='declined',resolved_at=utcnow()))
        if result.rowcount != 1:
            raise ChatError('Convite não encontrado.',404)


def cancel_group_request(user_id, conversation_id):
    conversation_id = identifier(conversation_id,'Grupo')
    db = get_db()
    with db:
        _lock_chat_user(db,user_id,session_actor=True)
        result = db.execute(update(GroupJoinRequest).where(
            GroupJoinRequest.conversation_id==conversation_id,
            GroupJoinRequest.user_id==user_id,GroupJoinRequest.status=='pending')
            .values(status='cancelled',resolved_at=utcnow()))
        if result.rowcount != 1:
            raise ChatError('Solicitação pendente não encontrada.',404)


def _transfer_group_owner(db, group, leaving_user_id):
    rows = db.execute(select(ConversationMember.user_id,ConversationMember.role,
        ConversationMember.joined_at).join(User,User.id==ConversationMember.user_id).where(
        ConversationMember.conversation_id==group['conversation_id'],
        ConversationMember.user_id!=leaving_user_id,User.active==1)
        .order_by(ConversationMember.joined_at,ConversationMember.user_id)).fetchall()
    successor = next((row for row in rows if row['role']=='moderator'),rows[0] if rows else None)
    now = utcnow()
    if successor is None:
        db.execute(update(GroupChat).where(GroupChat.conversation_id==group['conversation_id'])
            .values(owner_id=None,archived=1,updated_at=now))
        return None
    db.execute(update(GroupChat).where(GroupChat.conversation_id==group['conversation_id'])
        .values(owner_id=successor['user_id'],updated_at=now))
    db.execute(update(ConversationMember).where(ConversationMember.conversation_id==group['conversation_id'],
        ConversationMember.user_id==successor['user_id']).values(role='owner'))
    db.execute(update(ConversationMember).where(ConversationMember.conversation_id==group['conversation_id'],
        ConversationMember.user_id==leaving_user_id).values(role='member'))
    return successor['user_id']


def leave_group(user_id, conversation_id):
    conversation_id = identifier(conversation_id,'Grupo')
    db = get_db()
    with db:
        _lock_chat_user(db,user_id,session_actor=True)
        db.execute(update(GroupChat).where(GroupChat.conversation_id==conversation_id)
            .values(updated_at=GroupChat.updated_at))
        group = _require_group(db,conversation_id)
        member = db.execute(select(ConversationMember.__table__).where(
            ConversationMember.conversation_id==conversation_id,ConversationMember.user_id==user_id)).fetchone()
        if member is None:
            raise ChatError('Você não participa deste grupo.',404)
        if group['owner_id']==user_id:
            _transfer_group_owner(db,group,user_id)
        db.execute(delete(ConversationMember).where(ConversationMember.conversation_id==conversation_id,
            ConversationMember.user_id==user_id))
        db.execute(update(GroupInvite).where(GroupInvite.conversation_id==conversation_id,
            GroupInvite.invitee_id==user_id,GroupInvite.status=='pending').values(status='cancelled',resolved_at=utcnow()))
        db.execute(update(GroupJoinRequest).where(GroupJoinRequest.conversation_id==conversation_id,
            GroupJoinRequest.user_id==user_id,GroupJoinRequest.status=='pending').values(status='cancelled',resolved_at=utcnow()))


def remove_group_member(actor_id, conversation_id, target_id):
    conversation_id = identifier(conversation_id,'Grupo')
    target_id = identifier(target_id,'Pessoa')
    db = get_db()
    with db:
        _require_group_role(db,actor_id,conversation_id)
        target = db.execute(select(ConversationMember.role).where(
            ConversationMember.conversation_id==conversation_id,
            ConversationMember.user_id==target_id)).fetchone()
        if target is None:
            raise ChatError('Participante não encontrado.',404)
        if target['role']=='owner':
            raise ChatError('Transfira a propriedade antes de remover o proprietário.',403)
        db.execute(delete(ConversationMember).where(ConversationMember.conversation_id==conversation_id,
            ConversationMember.user_id==target_id))
        db.execute(update(GroupInvite).where(GroupInvite.conversation_id==conversation_id,
            GroupInvite.invitee_id==target_id,GroupInvite.status=='pending').values(status='cancelled',resolved_at=utcnow()))
        db.execute(update(GroupJoinRequest).where(GroupJoinRequest.conversation_id==conversation_id,
            GroupJoinRequest.user_id==target_id,GroupJoinRequest.status=='pending').values(status='cancelled',resolved_at=utcnow()))


def set_group_role(actor_id, conversation_id, target_id, role):
    conversation_id = identifier(conversation_id,'Grupo')
    target_id = identifier(target_id,'Pessoa')
    if role not in ('moderator','member'):
        raise ChatError('Escolha um papel disponível.')
    db = get_db()
    with db:
        group, _ = _require_group_role(db,actor_id,conversation_id,roles=('owner',))
        if target_id == group['owner_id']:
            raise ChatError('O proprietário mantém o papel de proprietário.')
        result = db.execute(update(ConversationMember).where(
            ConversationMember.conversation_id==conversation_id,
            ConversationMember.user_id==target_id).values(role=role))
        if result.rowcount != 1:
            raise ChatError('Participante não encontrado.',404)


def update_group(actor_id, conversation_id, changes):
    conversation_id = identifier(conversation_id,'Grupo')
    allowed = {'name','description','mode','minimum_level','visual_token'}
    if not isinstance(changes,dict) or set(changes)-allowed:
        raise ChatError('Configurações de grupo inválidas.')
    db = get_db()
    with db:
        _require_group_role(db,actor_id,conversation_id)
        values = {}
        if 'name' in changes:
            name = changes['name']
            if not storable_text(name) or not 3 <= len(name.strip()) <= 60:
                raise ChatError('O nome do grupo deve ter entre 3 e 60 caracteres.')
            values.update(name=name.strip(),slug=_group_slug(name.strip()))
        if 'description' in changes:
            description = changes['description']
            if not storable_text(description or '') or len((description or '').strip()) > 500:
                raise ChatError('A descrição pode ter até 500 caracteres.')
            values['description'] = (description or '').strip()
        if 'mode' in changes:
            if changes['mode'] not in ('open','closed'):
                raise ChatError('Escolha um modo de entrada válido.')
            values['mode'] = changes['mode']
            if changes['mode']=='open':
                db.execute(update(GroupJoinRequest).where(GroupJoinRequest.conversation_id==conversation_id,
                    GroupJoinRequest.status=='pending').values(status='cancelled',resolved_at=utcnow()))
        if 'minimum_level' in changes:
            try:
                level = identifier(changes['minimum_level'],'Nível mínimo')
            except ChatError:
                raise ChatError('O nível mínimo deve ser um inteiro positivo.') from None
            if level > 999:
                raise ChatError('O nível mínimo não pode ultrapassar 999.')
            values['minimum_level'] = level
        if 'visual_token' in changes:
            if not isinstance(changes['visual_token'],str) or changes['visual_token'] not in GROUP_VISUALS:
                raise ChatError('Escolha uma identidade visual disponível.')
            values['visual_token'] = changes['visual_token']
        values['updated_at'] = utcnow()
        db.execute(update(GroupChat).where(GroupChat.conversation_id==conversation_id).values(**values))
    return conversation_summary(actor_id,conversation_id)


def moderate_group_message(actor_id, message_id):
    message_id = identifier(message_id,'Mensagem')
    db = get_db()
    with db:
        message = db.execute(select(Message.__table__).where(Message.id==message_id)).fetchone()
        if message is None:
            raise ChatError('Mensagem não encontrada.',404)
        _require_group_role(db,actor_id,message['conversation_id'])
        if message['redacted_at'] is None:
            db.execute(update(Message).where(Message.id==message_id).values(
                redacted_at=utcnow(),redacted_by=actor_id))


def handle_user_deletion(db, user_id):
    groups = db.execute(select(GroupChat.__table__).where(GroupChat.owner_id==user_id,
        GroupChat.archived==0)).fetchall()
    for group in groups:
        _transfer_group_owner(db,group,user_id)
    db.execute(delete(ConversationMember).where(ConversationMember.user_id==user_id))
    db.execute(delete(GroupJoinRequest).where(GroupJoinRequest.user_id==user_id))
    db.execute(delete(GroupInvite).where(or_(GroupInvite.invitee_id==user_id,
        GroupInvite.inviter_id==user_id)))


def identifier(value, name='Identificador'):
    if isinstance(value, bool):
        raise ChatError(f'{name} inválido.')
    try:
        result = int(value)
    except (TypeError, ValueError, OverflowError):
        raise ChatError(f'{name} inválido.') from None
    if result < 1 or result > 2 ** 63 - 1 or str(result) != str(value):
        raise ChatError(f'{name} inválido.')
    return result


def public_user(row):
    return {'id': row['id'], 'username': row['username'], 'name': row['nome'],
        'avatar_url': image_url('avatar', row['imagem'])} if row else None


def _lock_people(first_id, second_id):
    # Social blocking uses the same ordered locks on PostgreSQL. Acquire both
    # before updating a sender, so opposite-direction sends cannot deadlock.
    db = get_db()
    if db.dialect == 'sqlite':
        db.execute(update(User).where(User.id.in_((first_id, second_id)))
                   .values(session_version=User.session_version))
    else:
        db.execute(select(User.id).where(User.id.in_((first_id, second_id)))
            .order_by(User.id).with_for_update()).fetchall()


def message_allowed(sender_id, recipient_id):
    """Check only the destination's current incoming-message preference."""
    from criticard.settings.service import get_preferences
    from criticard.social.models import Friend
    policy = get_preferences(recipient_id)['message_policy']
    if policy == 'all':
        return True
    if policy == 'nobody':
        return False
    low, high = sorted((sender_id, recipient_id))
    accepted = get_db().execute(select(Friend.id).where(and_(
        Friend.user_low_id == low, Friend.user_high_id == high, Friend.status == 'accepted'))).scalar()
    return accepted is not None


def _message_allowed(sender_id, recipient_id):
    if not message_allowed(sender_id, recipient_id):
        raise ChatError('Esta pessoa não está recebendo mensagens de você.', 403)


def membership(user_id, conversation_id, *, sending=False):
    conversation_id = identifier(conversation_id, 'Conversa')
    db = get_db()
    kind = db.execute(select(Conversation.kind).where(Conversation.id == conversation_id)).scalar()
    if kind is None:
        raise ChatError('Conversa não encontrada.',404)
    member = db.execute(select(ConversationMember.__table__).where(
        ConversationMember.conversation_id == conversation_id, ConversationMember.user_id == user_id)).fetchone()
    if not member:
        raise ChatError('Conversa não encontrada.', 404)
    if kind == 'group':
        _require_group(db,conversation_id)
        return member, None
    peer = db.execute(select(User.id, User.username, User.nome, User.imagem, User.active).join(
        ConversationMember, ConversationMember.user_id == User.id).where(
        ConversationMember.conversation_id == conversation_id, ConversationMember.user_id != user_id)).fetchone()
    if peer and users_blocked(user_id, peer['id']):
        raise ChatError('Esta conversa está indisponível.', 403)
    if sending and (not peer or peer['active'] != 1):
        raise ChatError('Não é possível enviar mensagens para esta conta.', 403)
    if sending:
        _message_allowed(user_id, peer['id'])
    return member, public_user(peer)


def start_conversation(user_id, target_id):
    target_id = identifier(target_id, 'Pessoa')
    if target_id == user_id:
        raise ChatError('Escolha outra pessoa para conversar.')
    db = get_db()
    low, high = sorted((user_id, target_id))
    existing = select(Conversation.id).where(Conversation.pair_low_id == low, Conversation.pair_high_id == high)
    try:
        with db:
            _lock_people(user_id, target_id)
            if db.dialect == 'sqlite':
                db.execute(update(User).where(User.id == user_id).values(session_version=User.session_version))
            if not db.execute(select(User.id).where(User.id == target_id, User.active == 1)).fetchone():
                raise ChatError('Pessoa não encontrada.', 404)
            if users_blocked(user_id, target_id):
                raise ChatError('Não é possível iniciar esta conversa.', 403)
            _message_allowed(user_id, target_id)
            conversation_id = db.execute(existing).scalar()
            if conversation_id:
                return conversation_summary(user_id, conversation_id), False
            conversation_id = db.execute(insert(Conversation).values(
                pair_low_id=low, pair_high_id=high, created_at=utcnow()).returning(Conversation.id)).scalar()
            db.execute(insert(ConversationMember), [
                {'conversation_id': conversation_id, 'user_id': user_id},
                {'conversation_id': conversation_id, 'user_id': target_id}])
    except IntegrityError:
        # The normalized unique pair is the arbiter of concurrent starts.
        conversation_id = db.execute(existing).scalar()
        if not conversation_id:
            raise
        return conversation_summary(user_id, conversation_id), False
    return conversation_summary(user_id, conversation_id), True


def _message(row):
    created_at = row['created_at']
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    sender = None if row['sender_id'] is None else {
        'id': row['sender_id'], 'username': row['username'], 'name': row['nome']}
    redacted = bool(row['redacted_at']) if 'redacted_at' in row else False
    return {'id': row['id'], 'conversation_id': row['conversation_id'],
        'body': 'Mensagem removida pela moderação.' if redacted else row['body'], 'redacted': redacted,
        'client_nonce': row['client_nonce'], 'created_at': created_at.isoformat(), 'sender': sender}


def message_query():
    return select(Message.__table__, User.username, User.nome).outerjoin(User, User.id == Message.sender_id)


def history(user_id, conversation_id, *, before_id=None, after_id=None, limit=50):
    membership(user_id, conversation_id)
    if before_id is not None and after_id is not None:
        raise ChatError('Use apenas um cursor de mensagens.')
    limit = min(identifier(limit, 'Limite'), 100)
    statement = message_query().where(Message.conversation_id == conversation_id)
    if before_id is not None:
        statement = statement.where(Message.id < identifier(before_id, 'Cursor'))
    if after_id is not None:
        statement = statement.where(Message.id > identifier(after_id, 'Cursor'))
        statement = statement.order_by(Message.id.asc())
    else:
        statement = statement.order_by(Message.id.desc())
    rows = get_db().execute(statement.limit(limit + 1)).fetchall()
    more = len(rows) > limit
    rows = rows[:limit]
    if after_id is None:
        rows.reverse()
    messages = [_message(row) for row in rows]
    return {'messages': messages, 'has_more': more,
        'before_id': messages[0]['id'] if messages else None,
        'after_id': messages[-1]['id'] if messages else None}


def unread_count(user_id, conversation_id, last_read_id):
    return get_db().execute(select(func.count()).select_from(Message).where(
        Message.conversation_id == conversation_id,
        or_(Message.sender_id != user_id, Message.sender_id.is_(None)),
        Message.id > (last_read_id or 0))).scalar()


def conversation_summary(user_id, conversation_id, *, group_details=True):
    member, peer = membership(user_id, conversation_id)
    latest = get_db().execute(message_query().where(Message.conversation_id == conversation_id)
        .order_by(Message.id.desc()).limit(1)).fetchone()
    kind = get_db().execute(select(Conversation.kind).where(Conversation.id == conversation_id)).scalar()
    group = group_summary(user_id,conversation_id,include_members=group_details) if kind == 'group' else None
    return {'id': conversation_id, 'kind': kind, 'group': group, 'peer': peer, 'last_read_id': member['last_read_id'],
        'unread_count': unread_count(user_id, conversation_id, member['last_read_id']),
        'last_message': _message(latest) if latest else None}


def conversations(user_id):
    db = get_db()
    rows = db.execute(select(Conversation.id, Conversation.kind, ConversationMember.last_read_id,
        ConversationMember.role, GroupChat.__table__).select_from(Conversation).join(
            ConversationMember, ConversationMember.conversation_id == Conversation.id).outerjoin(
            GroupChat, and_(GroupChat.conversation_id == Conversation.id, Conversation.kind == 'group'))
        .where(ConversationMember.user_id == user_id).order_by(Conversation.id.desc())).fetchall()
    visible_rows = []
    for row in rows:
        if row['kind'] == 'group':
            if row['conversation_id'] is None:
                raise ChatError('Grupo não encontrado.', 404)
            if row['archived']:
                continue
        visible_rows.append(row)

    # Load direct peers together, checking both directions of blocking before
    # fetching message previews or unread counts for the visible conversations.
    peers = {}
    direct_ids = [row['id'] for row in visible_rows if row['kind'] != 'group']
    if direct_ids:
        blocked = select(Block.id).where(or_(
            and_(Block.user_id == user_id, Block.target_id == User.id),
            and_(Block.user_id == User.id, Block.target_id == user_id))).exists()
        peer_rows = db.execute(select(ConversationMember.conversation_id, User.id,
            User.username, User.nome, User.imagem, blocked.label('blocked')).select_from(
                ConversationMember).join(User, User.id == ConversationMember.user_id).where(
                ConversationMember.conversation_id.in_(direct_ids),
                ConversationMember.user_id != user_id)).fetchall()
        for peer in peer_rows:
            peers.setdefault(peer['conversation_id'], peer)
    visible_rows = [row for row in visible_rows
        if not (peers.get(row['id']) and peers[row['id']]['blocked'])]
    ids = [row['id'] for row in visible_rows]
    if not ids:
        return {'conversations': [], 'unread_count': 0}

    latest_ids = select(func.max(Message.id)).where(Message.conversation_id.in_(ids))
    latest_ids = latest_ids.group_by(Message.conversation_id).correlate(None)
    latest = {row['conversation_id']: row for row in db.execute(
        message_query().where(Message.id.in_(latest_ids))).fetchall()}
    unread = {row['conversation_id']: row['unread_count'] for row in db.execute(
        select(Message.conversation_id, func.count().label('unread_count')).join(
            ConversationMember, ConversationMember.conversation_id == Message.conversation_id).where(
            ConversationMember.user_id == user_id, Message.conversation_id.in_(ids),
            or_(Message.sender_id != user_id, Message.sender_id.is_(None)),
            Message.id > func.coalesce(ConversationMember.last_read_id, 0))
        .group_by(Message.conversation_id)).fetchall()}
    group_ids = [row['id'] for row in visible_rows if row['kind'] == 'group']
    group_counts = {}
    if group_ids:
        group_counts = {row['conversation_id']: row['member_count'] for row in db.execute(
            select(ConversationMember.conversation_id, func.count().label('member_count')).join(
                User, User.id == ConversationMember.user_id).where(
                ConversationMember.conversation_id.in_(group_ids), User.active == 1)
            .group_by(ConversationMember.conversation_id)).fetchall()}

    items = []
    for row in visible_rows:
        conversation_id = row['id']
        group = _group_summary_data(user_id, row, row['role'], group_counts.get(conversation_id, 0),
            [], []) if row['kind'] == 'group' else None
        message = latest.get(conversation_id)
        items.append({'id': conversation_id, 'kind': row['kind'], 'group': group,
            'peer': public_user(peers.get(conversation_id)), 'last_read_id': row['last_read_id'],
            'unread_count': unread.get(conversation_id, 0),
            'last_message': _message(message) if message else None})
    items.sort(key=lambda item: item['last_message']['id'] if item['last_message'] else 0, reverse=True)
    return {'conversations': items, 'unread_count': sum(item['unread_count'] for item in items)}


def group_summary(user_id, conversation_id, *, include_members=True):
    group = _require_group(get_db(),conversation_id)
    if include_members:
        member_rows = get_db().execute(select(ConversationMember.role, ConversationMember.joined_at,
            User.id,User.username,User.nome,User.imagem).join(User,User.id==ConversationMember.user_id).where(
            ConversationMember.conversation_id==conversation_id,User.active==1)
            .order_by(ConversationMember.joined_at,User.id)).fetchall()
        members = [dict(id=row['id'],username=row['username'],name=row['nome'],
            avatar_url=image_url('avatar',row['imagem']),role=row['role'],joined_at=row['joined_at'])
            for row in member_rows]
        own = next((row for row in members if row['id']==user_id),None)
        member_count = len(members)
    else:
        own = get_db().execute(select(ConversationMember.role).where(
            ConversationMember.conversation_id==conversation_id,
            ConversationMember.user_id==user_id)).fetchone()
        member_count = get_db().execute(select(func.count()).select_from(ConversationMember).join(
            User,User.id==ConversationMember.user_id).where(
            ConversationMember.conversation_id==conversation_id,User.active==1)).scalar()
        members = []
    requests = []
    if include_members and own and own['role'] in ('owner','moderator'):
        requests = get_db().execute(select(GroupJoinRequest.__table__,User.username,User.nome).join(
            User,User.id==GroupJoinRequest.user_id).where(
            GroupJoinRequest.conversation_id==conversation_id,GroupJoinRequest.status=='pending')
            .order_by(GroupJoinRequest.created_at,GroupJoinRequest.id)).fetchall()
    return _group_summary_data(user_id, group, own['role'] if own else 'member', member_count,
        members, requests)


def _group_summary_data(user_id, group, role, member_count, members, requests):
    return {'id':group['conversation_id'],'name':group['name'],'slug':group['slug'],
        'description':group['description'],'mode':group['mode'],'minimum_level':group['minimum_level'],
        'visual_token':group['visual_token'],'owner_id':group['owner_id'],
        'archived':bool(group['archived']),'created_at':group['created_at'],
        'member_count':member_count,'members':members,'pending_requests':requests,
        'role':role,
        'is_owner':group['owner_id']==user_id}


def _consume_send_limit(db, user_id):
    now = time()
    limit = current_app.config.get('CHAT_RATE_LIMIT', 30)
    window = current_app.config.get('CHAT_RATE_WINDOW', 60)
    attempt = db.execute(select(ChatRateAttempt.__table__).where(ChatRateAttempt.user_id == user_id)).fetchone()
    if not attempt:
        db.execute(insert(ChatRateAttempt).values(user_id=user_id, attempts=1, expires=now + window))
    elif attempt['expires'] <= now:
        db.execute(update(ChatRateAttempt).where(ChatRateAttempt.user_id == user_id)
            .values(attempts=1, expires=now + window))
    elif attempt['attempts'] >= limit:
        raise ChatError('Aguarde um minuto antes de enviar mais mensagens.', 429)
    else:
        db.execute(update(ChatRateAttempt).where(ChatRateAttempt.user_id == user_id)
            .values(attempts=ChatRateAttempt.attempts + 1))


def send_message(user_id, conversation_id, body, client_nonce, *, expected_version=None):
    if not storable_text(body) or not body.strip() or len(body) > 2000:
        raise ChatError('Escreva uma mensagem de até 2000 caracteres.')
    try:
        nonce = str(UUID(client_nonce))
    except (ValueError, TypeError, AttributeError):
        raise ChatError('Identificador de envio inválido.') from None
    db = get_db()
    _, peer = membership(user_id, conversation_id, sending=True)
    with db:
        if peer:
            _lock_people(user_id, peer['id'])
        else:
            db.execute(update(User).where(User.id==user_id).values(session_version=User.session_version))
        # Lock the sender row on both engines before idempotency and rate checks.
        # A harmless UPDATE also serializes SQLite writers without mutable globals.
        lock = update(User).where(User.id == user_id, User.active == 1)
        if expected_version is not None:
            lock = lock.where(User.session_version == expected_version)
        user = db.execute(lock.values(session_version=User.session_version).returning(User.id)).fetchone()
        if not user:
            raise ChatError('Faça login novamente.', 401)
        membership(user_id, conversation_id, sending=True)
        duplicate = db.execute(message_query().where(Message.sender_id == user_id,
            Message.conversation_id == conversation_id, Message.client_nonce == nonce)).fetchone()
        if duplicate:
            return _message(duplicate), False
        _consume_send_limit(db, user_id)
        message_id = db.execute(insert(Message).values(conversation_id=conversation_id,
            sender_id=user_id, body=body, client_nonce=nonce, created_at=utcnow()).returning(Message.id)).scalar()
        message = db.execute(message_query().where(Message.id == message_id)).fetchone()
    # No caller may acknowledge or publish until the transaction has committed.
    return _message(message), True


def mark_read(user_id, conversation_id, message_id):
    membership(user_id, conversation_id)
    message_id = identifier(message_id, 'Mensagem')
    db = get_db()
    if not db.execute(select(Message.id).where(Message.id == message_id,
        Message.conversation_id == conversation_id)).fetchone():
        raise ChatError('Mensagem não encontrada nesta conversa.', 404)
    with db:
        db.execute(update(ConversationMember).where(ConversationMember.user_id == user_id,
            ConversationMember.conversation_id == conversation_id,
            or_(ConversationMember.last_read_id.is_(None), ConversationMember.last_read_id < message_id))
            .values(last_read_id=message_id))
    return conversation_summary(user_id, conversation_id)
