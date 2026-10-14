"""Persistent form budgets and browser response protections."""
import hashlib
import hmac
import math
import time

from flask import current_app, request

from .db import get_db
from .models import FormAttempt
from sqlalchemy import delete, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.dialects.postgresql import insert as postgres_insert


def attempt_budget(scope):
    """Consume one attempt atomically, returning seconds to wait when exhausted."""
    config = current_app.config
    limit = config[f"{scope.upper()}_ATTEMPT_LIMIT"]
    window = config[f"{scope.upper()}_ATTEMPT_WINDOW"]
    now = time.time()
    # Only the actual peer is trusted. A future reverse proxy must be configured
    # explicitly before using forwarded client addresses.
    key = hmac.new(config["SECRET_KEY"].encode(), (request.remote_addr or "unknown").encode(), hashlib.sha256).hexdigest()
    db = get_db()
    with db:
        db.execute(delete(FormAttempt).where(FormAttempt.expires <= now))
        create = sqlite_insert if db.dialect == 'sqlite' else postgres_insert
        statement = create(FormAttempt).values(scope=scope,client_key=key,attempts=1,expires=now + window)
        consumed = db.execute(statement.on_conflict_do_update(
            index_elements=[FormAttempt.scope,FormAttempt.client_key],
            set_={'attempts':FormAttempt.attempts + 1},where=FormAttempt.attempts < limit
        ).returning(FormAttempt.expires)).fetchone()
        if consumed:
            return 0
        expires = db.execute(select(FormAttempt.expires).where(FormAttempt.scope == scope,FormAttempt.client_key == key)).scalar()
    return max(1, math.ceil(expires - now))


def secure_response(response):
    from .storage import public_image_origin
    image_origin = public_image_origin()
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self'; "
        f"img-src 'self' blob: data:{' ' + image_origin if image_origin else ''}; font-src 'self'; connect-src 'self'; "
        "object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    if current_app.config.get('ENVIRONMENT') == 'production':
        response.headers['Strict-Transport-Security'] = 'max-age=31536000'
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    if response.mimetype == "text/html":
        response.headers["Cache-Control"] = "no-store"
    return response


def init_app(app):
    app.after_request(secure_response)
