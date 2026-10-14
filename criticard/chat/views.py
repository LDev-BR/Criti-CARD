"""Private chat pages and CSRF-protected JSON/form endpoints."""
from uuid import uuid4
from dataclasses import asdict

from flask import Blueprint, g, jsonify, redirect, render_template, request, url_for
from sqlalchemy import select

from criticard.db import get_db
from criticard.models import User
from criticard.models import utcnow
from criticard.progression.access import evaluate_social_access
from criticard.security import login_required
from criticard.validation import storable_text
from . import service
from .sockets import publish_message

bp = Blueprint('chat', __name__)


def wants_json():
    return request.is_json or request.accept_mimetypes.best == 'application/json'


def payload():
    data = request.get_json(silent=True) if request.is_json else request.form
    if not hasattr(data, 'get'):
        raise service.ChatError('Dados da mensagem inválidos.')
    return data


@bp.errorhandler(service.ChatError)
def chat_error(error):
    if wants_json() or request.endpoint == 'chat.history':
        return jsonify(error=str(error)), error.status
    return render_template('error.html', code=error.status, message=str(error)), error.status


@bp.get('/mensagens')
@login_required
def index():
    data = service.conversations(g.user['id'])
    return jsonify(data) if wants_json() else render_template('chat/index.html', **data)


@bp.get('/mensagens/grupos')
@login_required
def groups():
    data = service.discover_group_chats(g.user['id'],request.args.get('q',''))
    access = evaluate_social_access(get_db(),g.user['id'],'create_group_chat',utcnow())
    context = dict(**data,create_access=asdict(access),visuals=sorted(service.GROUP_VISUALS),
        search=request.args.get('q',''))
    return jsonify(context) if wants_json() else render_template('chat/groups.html',**context)


@bp.post('/mensagens/grupos/criar')
@login_required
def create_group():
    data = payload()
    group = service.create_group_chat(g.user['id'],data.get('name',''),data.get('description',''),
        data.get('mode','open'),data.get('minimum_level',1),data.get('visual_token','gold'))
    if wants_json():
        return jsonify(group=group),201
    return redirect(url_for('chat.detail',conversation_id=group['id']))


@bp.post('/mensagens/grupos/<int:conversation_id>/entrar')
@login_required
def join_group(conversation_id):
    member = service.join_open_group(g.user['id'],conversation_id)
    return jsonify(member=member) if wants_json() else redirect(url_for('chat.detail',conversation_id=conversation_id))


@bp.post('/mensagens/grupos/<int:conversation_id>/solicitar')
@login_required
def request_group_access(conversation_id):
    request_row = service.request_closed_group_access(g.user['id'],conversation_id)
    if wants_json():
        return jsonify(request=request_row),202
    return redirect(url_for('chat.groups'))


@bp.post('/mensagens/grupos/convites/<int:invite_id>/aceitar')
@login_required
def accept_group_invite(invite_id):
    member = service.accept_group_invite(g.user['id'],invite_id)
    conversation_id = member['conversation_id']
    return jsonify(member=member) if wants_json() else redirect(url_for('chat.detail',conversation_id=conversation_id))


@bp.post('/mensagens/grupos/convites/<int:invite_id>/recusar')
@login_required
def decline_group_invite(invite_id):
    service.decline_group_invite(g.user['id'],invite_id)
    return jsonify(declined=True) if wants_json() else redirect(url_for('chat.groups'))


@bp.post('/mensagens/grupos/<int:conversation_id>/cancelar-solicitacao')
@login_required
def cancel_group_request(conversation_id):
    service.cancel_group_request(g.user['id'],conversation_id)
    return jsonify(cancelled=True) if wants_json() else redirect(url_for('chat.groups'))


@bp.post('/mensagens/grupos/<int:conversation_id>/sair')
@login_required
def leave_group(conversation_id):
    service.leave_group(g.user['id'],conversation_id)
    return jsonify(left=True) if wants_json() else redirect(url_for('chat.index'))


@bp.post('/mensagens/grupos/<int:conversation_id>/convidar')
@login_required
def invite_group(conversation_id):
    data = payload()
    target = data.get('target_id')
    if target is None:
        username = data.get('target_username','')
        if not storable_text(username) or not username.strip():
            raise service.ChatError('Informe o nome de usuário da pessoa.')
        target = get_db().execute(select(User.id).where(
            User.username==username.strip().lstrip('@').upper())).scalar()
        if target is None:
            raise service.ChatError('Pessoa não encontrada.',404)
    invite = service.invite_group_member(g.user['id'],conversation_id,target)
    if wants_json():
        return jsonify(invite=invite),201
    return redirect(url_for('chat.detail',conversation_id=conversation_id))


@bp.post('/mensagens/grupos/solicitacoes/<int:request_id>')
@login_required
def resolve_group_request(request_id):
    value = payload().get('approve','false')
    approve = value is True or value in ('true','1','approve')
    member = service.approve_group_request(g.user['id'],request_id,approve)
    if wants_json():
        return jsonify(member=member,approved=approve)
    return redirect(url_for('chat.detail',conversation_id=member['conversation_id']) if member else url_for('chat.index'))


@bp.post('/mensagens/grupos/<int:conversation_id>/participantes/<int:target_id>/remover')
@login_required
def remove_group_member(conversation_id,target_id):
    service.remove_group_member(g.user['id'],conversation_id,target_id)
    return jsonify(removed=True) if wants_json() else redirect(url_for('chat.detail',conversation_id=conversation_id))


@bp.post('/mensagens/grupos/<int:conversation_id>/participantes/<int:target_id>/papel')
@login_required
def set_group_role(conversation_id,target_id):
    service.set_group_role(g.user['id'],conversation_id,target_id,payload().get('role'))
    return jsonify(updated=True) if wants_json() else redirect(url_for('chat.detail',conversation_id=conversation_id))


@bp.post('/mensagens/grupos/<int:conversation_id>/configurar')
@login_required
def update_group(conversation_id):
    data = payload()
    changes = {field:data[field] for field in ('name','description','mode','minimum_level','visual_token') if field in data}
    group = service.update_group(g.user['id'],conversation_id,changes)
    return jsonify(group=group) if wants_json() else redirect(url_for('chat.detail',conversation_id=conversation_id))


@bp.post('/mensagens/grupos/mensagens/<int:message_id>/remover')
@login_required
def moderate_message(message_id):
    service.moderate_group_message(g.user['id'],message_id)
    return jsonify(removed=True) if wants_json() else redirect(request.referrer or url_for('chat.index'))


@bp.post('/mensagens/iniciar')
@login_required
def start():
    data = payload()
    target = data.get('target_id')
    if target is None:
        username = data.get('target_username', '')
        if not storable_text(username) or not username.strip():
            raise service.ChatError('Informe o nome de usuário da pessoa.')
        target = get_db().execute(select(User.id).where(User.username == username.strip().lstrip('@').upper())).scalar()
        if target is None:
            raise service.ChatError('Pessoa não encontrada.', 404)
    conversation, created = service.start_conversation(g.user['id'], target)
    if wants_json():
        return jsonify(conversation=conversation, created=created), 201 if created else 200
    return redirect(url_for('chat.detail', conversation_id=conversation['id']))


@bp.get('/mensagens/<int:conversation_id>')
@login_required
def detail(conversation_id):
    conversation = service.conversation_summary(g.user['id'], conversation_id)
    page = service.history(g.user['id'], conversation_id, before_id=request.args.get('before_id'))
    if wants_json():
        return jsonify(conversation=conversation, **page)
    return render_template('chat/detail.html', conversation=conversation, nonce=str(uuid4()),
        can_send=bool(conversation['kind']=='group' or (conversation['peer'] and service.message_allowed(g.user['id'], conversation['peer']['id']))),
        **page, **service.conversations(g.user['id']))


@bp.get('/mensagens/<int:conversation_id>/historico')
@login_required
def history(conversation_id):
    return jsonify(service.history(g.user['id'], conversation_id,
        before_id=request.args.get('before_id'), after_id=request.args.get('after_id'),
        limit=request.args.get('limit', 50)))


@bp.post('/mensagens/<int:conversation_id>/enviar')
@login_required
def send(conversation_id):
    data = payload()
    message, created = service.send_message(g.user['id'], conversation_id,
        data.get('body'), data.get('client_nonce'), expected_version=g.user['session_version'])
    if created:
        publish_message(message)
    if wants_json():
        return jsonify(message=message, created=created), 201 if created else 200
    return redirect(url_for('chat.detail', conversation_id=conversation_id))


@bp.post('/mensagens/<int:conversation_id>/lida')
@login_required
def read(conversation_id):
    conversation = service.mark_read(g.user['id'], conversation_id, payload().get('message_id'))
    if wants_json():
        return jsonify(conversation=conversation)
    return redirect(url_for('chat.detail', conversation_id=conversation_id))
