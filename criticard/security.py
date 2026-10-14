"""Current-user loading, access controls and CSRF protection."""
import hmac
import secrets
from functools import wraps

from flask import abort, current_app, flash, g, jsonify, redirect, request, session, url_for
from sqlalchemy import select

from .db import get_db
from .models import User


def wants_json():
    return request.is_json or request.accept_mimetypes.best == 'application/json'


def session_identity(user):
    """Bind cookies and sockets to this account's credentials, including reused IDs."""
    key = current_app.secret_key
    if isinstance(key, str):
        key = key.encode()
    payload = f"{user['id']}:{user['senha']}:{user['session_version']}".encode()
    return hmac.new(key, payload, 'sha256').hexdigest()


def valid_session_identity(user, session_data):
    supplied = session_data.get('auth_stamp')
    return bool(user and user['active'] and
                user['session_version'] == session_data.get('session_version') and
                isinstance(supplied, str) and hmac.compare_digest(session_identity(user), supplied))


def load_user():
    for legacy_key in ("user_senha", "user_admin", "user_nome"):
        session.pop(legacy_key, None)
    user_id = session.get("usuario_id")
    g.user = None
    if isinstance(user_id, int) and 1 <= user_id <= 2**63-1:
        g.user = get_db().execute(select(User).where(User.id == user_id, User.active == 1)).fetchone()
        if not valid_session_identity(g.user, session):
            g.user = None
    if user_id is not None and g.user is None:
        session.clear()


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            if wants_json():
                return jsonify(error='Faça login para continuar.'), 401
            flash("Faça login para continuar.", "error")
            from .navigation import safe_local_path
            destination = safe_local_path(request.full_path.rstrip('?')) if request.method in ('GET', 'HEAD') else None
            return redirect(url_for("auth.index", **({'next': destination} if destination else {})))
        return view(*args, **kwargs)
    return wrapped


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if g.user["admin"] != 1:
            abort(403)
        return view(*args, **kwargs)
    return wrapped


def csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return session["csrf_token"]


def protect_csrf():
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        expected = session.get("csrf_token", "")
        supplied = request.headers.get('X-CSRF-Token') or request.form.get("csrf_token", "")
        if not expected or not hmac.compare_digest(expected.encode(), supplied.encode()):
            abort(400)


def init_app(app):
    app.before_request(load_user)
    app.before_request(protect_csrf)
    app.context_processor(lambda: {"usuario_atual": g.user, "csrf_token": csrf_token})
