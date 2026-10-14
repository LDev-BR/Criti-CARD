"""Progressive forms and JSON endpoints call the same social services."""
from datetime import date, datetime

from flask import Blueprint, abort, flash, g, jsonify, redirect, render_template, request, url_for
from sqlalchemy import select
from ..models import Card, User
from ..queries import get_card
from ..security import admin_required, login_required
from ..progression.types import ProgressionError
from . import service

bp = Blueprint('social', __name__, url_prefix='/social')


@bp.after_request
def private_notifications(response):
    if request.path.startswith('/social/notifications'):
        response.headers['Cache-Control'] = 'no-store'
    return response


def wants_json():
    return request.is_json or request.accept_mimetypes.best == 'application/json'


def _serialized(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _serialized(item) for key, item in value.items() if key != 'event_key'}
    if isinstance(value, (tuple, list)):
        return [_serialized(item) for item in value]
    return value


def _payload():
    value = request.get_json() if request.is_json else request.form
    if not hasattr(value, 'get'):
        raise service.SocialError('Envie um objeto com os campos desta ação.')
    return value


def _boolean(field, default=None):
    value = _payload().get(field, default)
    if request.is_json:
        if not isinstance(value, bool):
            raise service.SocialError('Informe o estado desejado desta ação.')
        return value
    if value in ('true', '1', True):
        return True
    if value in ('false', '0', False):
        return False
    raise service.SocialError('Informe o estado desejado desta ação.')


def _result(data, target, message=None, status=200):
    if wants_json():
        return jsonify(_serialized(data)), status
    if message:
        flash(message, 'success')
    return redirect(target)


def _public_card(card_id):
    card = get_card(card_id)
    if card['archived']:
        abort(404)
    return card


def _profile_link(user_id):
    user = service._require(User, user_id)
    return url_for('community.profile', username=user['username'])


def _page():
    return max(1, request.args.get('page', 1, type=int) or 1)


@bp.errorhandler(service.SocialError)
@bp.errorhandler(ProgressionError)
def social_error(error):
    if wants_json():
        return jsonify(error=str(error)), error.status
    return render_template('error.html', code=error.status, message=str(error)), error.status


@bp.route('/cards/<int:card_id>/like', methods=['POST', 'PUT', 'DELETE'])
@login_required
def like(card_id):
    liked = request.method != 'DELETE' and _boolean('liked', request.method == 'PUT')
    state = service.set_like(g.user['id'], card_id, liked)
    return _result(state, url_for('cards.detail', id=card_id))


@bp.route('/cards/<int:card_id>/comments', methods=['GET', 'POST'])
def comments(card_id):
    if request.method == 'POST':
        return _post_comment(card_id)
    card = _public_card(card_id)
    data = service.comments_for_card(card_id, _page())
    if wants_json():
        return jsonify(_serialized(data))
    return render_template('social/comments.html', c=card, card_comments=data,
        social_state=service.card_social_state([card_id], g.user['id'] if g.user else None)[card_id])


@login_required
def _post_comment(card_id):
    comment = service.create_comment(g.user['id'], card_id, _payload().get('body'))
    return _result({'comment': comment, **service.card_social_state([card_id], g.user['id'])[card_id]},
        url_for('social.comments', card_id=card_id), 'Comentário publicado.', 201)


@bp.route('/comments/<int:comment_id>/edit', methods=['GET', 'POST', 'PATCH'])
@login_required
def edit_comment(comment_id):
    comment = service._require(service.Comment, comment_id)
    if comment['author_id'] != g.user['id']:
        abort(403)
    if request.method == 'GET':
        _public_card(comment['card_id'])
        return render_template('social/edit_comment.html', comment=comment)
    edited = service.edit_comment(g.user['id'], comment_id, _payload().get('body'))
    return _result({'comment': edited}, url_for('social.comments', card_id=comment['card_id']), 'Comentário atualizado.')


@bp.route('/comments/<int:comment_id>/delete', methods=['POST', 'DELETE'])
@login_required
def delete_comment(comment_id):
    card_id = service.delete_comment(g.user['id'], comment_id, g.user['admin'] == 1)
    return _result({'deleted': True, 'card_id': card_id}, url_for('social.comments', card_id=card_id), 'Comentário excluído.')


@bp.route('/users/<int:user_id>/follow', methods=['POST', 'PUT', 'DELETE'])
@login_required
def follow(user_id):
    following = request.method != 'DELETE' and _boolean('following', request.method == 'PUT')
    data = service.set_follow(g.user['id'], user_id, following)
    return _result(data, _profile_link(user_id))


@bp.route('/works/<int:work_id>/follow', methods=['POST', 'PUT', 'DELETE'])
@login_required
def follow_work(work_id):
    following = request.method != 'DELETE' and _boolean('following', request.method == 'PUT')
    data = service.set_work_follow(g.user['id'], work_id, following)
    from ..models import Work
    work = service._require(Work, work_id)
    return _result(data, url_for('backlog.catalog', q=work['titulo']))


@bp.route('/categories/<int:category_id>/follow', methods=['POST', 'PUT', 'DELETE'])
@login_required
def follow_category(category_id):
    following = request.method != 'DELETE' and _boolean('following', request.method == 'PUT')
    data = service.set_category_follow(g.user['id'], category_id, following)
    from ..models import Category
    category = service._require(Category, category_id)
    return _result(data, url_for('backlog.catalog', categoria=category['slug']))


@bp.route('/users/<int:user_id>/block', methods=['POST', 'PUT', 'DELETE'])
@login_required
def block(user_id):
    blocked = request.method != 'DELETE' and _boolean('blocked', request.method == 'PUT')
    data = service.set_block(g.user['id'], user_id, blocked)
    return _result(data, _profile_link(user_id), 'Bloqueio atualizado.')


@bp.route('/reports', methods=['GET', 'POST'])
@login_required
def report():
    data = _payload() if request.method == 'POST' else request.args
    target_type = data.get('target_type', '')
    raw_id = data.get('target_id', 0)
    try:
        if type(raw_id) is not int and not (isinstance(raw_id, str) and raw_id.isdecimal()):
            raise ValueError('Invalid identity')
        target_id = int(raw_id)
        if not 1 <= target_id <= 2**63 - 1:
            raise ValueError('Invalid identity')
    except (ValueError, TypeError):
        raise service.SocialError('Informe um alvo válido para a denúncia.')
    if request.method == 'GET':
        if target_type in ('community_post', 'community_comment'):
            service._community_report_target(target_type, target_id, g.user['id'])
            return render_template('social/report.html', target_type=target_type, target_id=target_id)
        if target_type == 'chat_message':
            from ..db import get_db
            from ..chat.models import Conversation, Message
            from ..chat.service import ChatError, membership
            message = get_db().execute(select(Message.id,Message.conversation_id).join(
                Conversation,Conversation.id==Message.conversation_id).where(
                Message.id==target_id,Conversation.kind=='group')).fetchone()
            if message is None:
                raise service.SocialError('Mensagem de grupo não encontrada.',404)
            try:
                membership(g.user['id'],message['conversation_id'])
            except ChatError as error:
                raise service.SocialError(str(error),error.status) from None
            return render_template('social/report.html',target_type=target_type,target_id=target_id)
        model = {'card': Card, 'comment': service.Comment, 'user': User}.get(target_type)
        if model is None:
            raise service.SocialError('Escolha um card, comentário ou usuário para denunciar.')
        service._require(model, target_id)
        return render_template('social/report.html', target_type=target_type, target_id=target_id)
    created = service.create_report(g.user['id'], target_type, target_id, data.get('reason'))
    return _result({'report': created}, url_for('discovery.index'), 'Denúncia enviada à moderação.', 201)


@bp.get('/moderation')
@admin_required
def moderation():
    data = service.moderation_reports(_page())
    if wants_json():
        return jsonify(_serialized(data))
    return render_template('social/moderation.html', **data)


@bp.post('/reports/<int:report_id>/resolve')
@admin_required
def resolve_report(report_id):
    report = service.resolve_report(g.user['id'], report_id)
    return _result({'report': report}, url_for('social.moderation'), 'Denúncia resolvida.')


@bp.get('/notifications')
@login_required
def notifications():
    raw = request.args.get('page', '1')
    if not raw.isascii() or not raw.isdecimal() or len(raw) > 7:
        raise service.SocialError('Página de notificações não encontrada.', 404)
    data = service.notifications_for_user(g.user['id'], int(raw),
        state=request.args.get('state', 'all'), kind=request.args.get('kind', 'all'))
    if wants_json():
        return jsonify(_serialized(data))
    return render_template('social/notifications.html', **data)


@bp.get('/notifications/unread-count')
@login_required
def notification_count():
    from .notifications import snapshot
    return jsonify(snapshot(g.user['id']))


def _notification_return():
    from .notifications import filters
    selected = filters(request.form.get('state', 'all'), request.form.get('kind', 'all'))
    return url_for('social.notifications', **selected)


@bp.post('/notifications/<int:notification_id>/read')
@login_required
def read_notification(notification_id):
    destination = _notification_return()
    data = service.mark_notification_read(g.user['id'], notification_id)
    return _result(data, destination)


@bp.post('/notifications/<int:notification_id>/open')
@login_required
def open_notification(notification_id):
    data = service.mark_notification_read(g.user['id'], notification_id)
    return redirect(data['target_url'] or url_for('social.notifications'))


@bp.post('/notifications/read-all')
@login_required
def read_all_notifications():
    destination = _notification_return()
    data = service.mark_notification_read(g.user['id'])
    return _result(data, destination, 'Notificações marcadas como lidas.')
