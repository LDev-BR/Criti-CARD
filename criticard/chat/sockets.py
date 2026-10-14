"""Socket events authenticate independently of HTTP hooks."""
import hmac
from functools import wraps
from urllib.parse import urlsplit

from flask import current_app, request, session
from flask_socketio import SocketIO, disconnect
from sqlalchemy import select

from criticard.db import get_db
from criticard.models import User
from criticard.security import valid_session_identity
from . import service

socketio = SocketIO()
NAMESPACE = '/chat'


def _connections():
    return current_app.extensions['chat_connections']


def _user(user_id, version, stamp):
    if not isinstance(user_id, int) or isinstance(user_id, bool) or not 1 <= user_id <= 2 ** 63 - 1 \
            or not isinstance(version, int) or isinstance(version, bool):
        return None
    user = get_db().execute(select(User.id, User.active, User.session_version, User.senha).where(User.id == user_id)).fetchone()
    return user if valid_session_identity(user, {'session_version': version, 'auth_stamp': stamp}) else None


def _origin_allowed():
    origin = request.headers.get('Origin')
    if not origin:
        return True
    try:
        parsed = urlsplit(origin)
    except ValueError:
        return False
    return parsed.scheme == request.scheme and parsed.netloc.lower() == request.host.lower() \
        and not parsed.path and not parsed.query and not parsed.fragment


@socketio.on('connect', namespace=NAMESPACE)
def connect(auth):
    supplied = auth.get('csrf_token') if isinstance(auth, dict) else None
    expected = session.get('csrf_token')
    if not _origin_allowed() or not isinstance(supplied, str) or not isinstance(expected, str) \
            or not expected or not hmac.compare_digest(supplied.encode(), expected.encode()):
        return False
    user_id, version = session.get('usuario_id'), session.get('session_version')
    stamp = session.get('auth_stamp')
    if not _user(user_id, version, stamp):
        return False
    _connections()[request.sid] = {'user_id': user_id, 'version': version, 'stamp': stamp, 'joined': set()}


@socketio.on('disconnect', namespace=NAMESPACE)
def disconnected(reason=None):
    _connections().pop(request.sid, None)


def authenticated_event(handler):
    @wraps(handler)
    def wrapped(data=None):
        connection = _connections().get(request.sid)
        if not connection or not _user(connection['user_id'], connection['version'], connection['stamp']):
            disconnect(namespace=NAMESPACE)
            return {'ok': False, 'error': 'Faça login novamente.', 'code': 401}
        if not isinstance(data, dict):
            return {'ok': False, 'error': 'Dados da mensagem inválidos.', 'code': 400}
        try:
            conversation_id = service.identifier(data.get('conversation_id'), 'Conversa')
            return handler(connection, conversation_id, data)
        except service.ChatError as error:
            return {'ok': False, 'error': str(error), 'code': error.status}
    return wrapped


@socketio.on('join', namespace=NAMESPACE)
@authenticated_event
def join(connection, conversation_id, data):
    service.membership(connection['user_id'], conversation_id)
    # Subscribe before the history snapshot so messages created during the query
    # reach the client. Its stable message IDs deduplicate snapshot/live overlap.
    connection['joined'].add(conversation_id)
    page = service.history(connection['user_id'], conversation_id,
        after_id=data.get('after_id'), before_id=data.get('before_id'), limit=data.get('limit', 50))
    return {'ok': True, **page, 'conversation': service.conversation_summary(connection['user_id'], conversation_id)}


@socketio.on('send_message', namespace=NAMESPACE)
@authenticated_event
def send(connection, conversation_id, data):
    message, created = service.send_message(connection['user_id'], conversation_id,
        data.get('body'), data.get('client_nonce'), expected_version=connection['version'])
    if created:
        publish_message(message)
    return {'ok': True, 'created': created, 'message': message}


@socketio.on('mark_read', namespace=NAMESPACE)
@authenticated_event
def read(connection, conversation_id, data):
    conversation = service.mark_read(connection['user_id'], conversation_id, data.get('message_id'))
    return {'ok': True, 'conversation': conversation}


def publish_message(message):
    """Check each subscribed recipient at delivery, including current blocks."""
    conversation_id = message['conversation_id']
    for sid, connection in list(_connections().items()):
        if conversation_id not in connection['joined']:
            continue
        if not _user(connection['user_id'], connection['version'], connection['stamp']):
            socketio.server.disconnect(sid, namespace=NAMESPACE)
            continue
        try:
            service.membership(connection['user_id'], conversation_id)
        except service.ChatError:
            connection['joined'].discard(conversation_id)
            continue
        socketio.emit('message', {'message': message}, to=sid, namespace=NAMESPACE)


def init_app(app):
    app.extensions['chat_connections'] = {}
    socketio.init_app(app, async_mode='threading', cors_allowed_origins=None,
        max_http_buffer_size=16384, manage_session=True)
