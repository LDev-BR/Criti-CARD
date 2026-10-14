"""Atomic account link consumption and persistent abuse budgets."""
import hashlib
import hmac
import math
import re
import secrets
import time
from datetime import timedelta

from flask import current_app
from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from werkzeug.security import generate_password_hash

from criticard.db import get_db
from criticard.models import FormAttempt, User, utcnow
from criticard.validation import FormValidationError, senha_forte, storable_text
from .models import AccountToken
from . import mail

RECOVERY_MESSAGE = "Se este email estiver cadastrado, você receberá as instruções para redefinir sua senha."
VERIFICATION_MESSAGE = "Se sua conta precisar de verificação, enviaremos um novo link para seu email."


class InvalidAccountToken(ValueError):
    pass


def _email(value):
    return value.strip().lower()[:254] if storable_text(value) else ""


def _digest(raw):
    if not isinstance(raw, str) or re.fullmatch(r"[A-Za-z0-9_-]{43}", raw) is None:
        raise InvalidAccountToken("Este link é inválido ou expirou.")
    return hashlib.sha256(raw.encode()).hexdigest()


def _budget(purpose, email, client_ip):
    now = time.time()
    window = int(current_app.config.get("ACCOUNT_RATE_WINDOW", 900))
    limits = (("ip", current_app.config.get("RESET_IP_LIMIT" if purpose == "reset" else "VERIFY_IP_LIMIT", 5 if purpose == "reset" else 10), client_ip or "unknown"),
              ("email", current_app.config.get("RESET_EMAIL_LIMIT" if purpose == "reset" else "VERIFY_EMAIL_LIMIT", 3), email))
    db = get_db()
    create = sqlite_insert if db.dialect == "sqlite" else pg_insert
    retry = 0
    with db:
        db.execute(delete(FormAttempt).where(FormAttempt.expires <= now))
        for kind, limit, value in limits:
            scope = "accounts_" + purpose + "_" + kind
            key = hmac.new(str(current_app.config["SECRET_KEY"]).encode(), str(value).encode(), hashlib.sha256).hexdigest()
            statement = create(FormAttempt).values(scope=scope, client_key=key, attempts=1, expires=now + window)
            consumed = db.execute(statement.on_conflict_do_update(
                index_elements=[FormAttempt.scope, FormAttempt.client_key],
                set_={"attempts": FormAttempt.attempts + 1}, where=FormAttempt.attempts < int(limit)
            ).returning(FormAttempt.expires)).fetchone()
            if consumed is None:
                expires = db.execute(select(FormAttempt.expires).where(FormAttempt.scope == scope, FormAttempt.client_key == key)).scalar()
                retry = max(retry, max(1, math.ceil(expires - now)))
    return retry


def _issue(user, purpose):
    if not mail.configured():
        return
    raw = secrets.token_urlsafe(32)
    ttl = int(current_app.config.get("RESET_TOKEN_TTL_SECONDS" if purpose == "reset" else "VERIFY_TOKEN_TTL_SECONDS", 1800 if purpose == "reset" else 86400))
    db = get_db()
    with db:
        token_id = db.execute(insert(AccountToken).values(user_id=user["id"], token_hash=_digest(raw), purpose=purpose,
                             email_snapshot=user["email"], session_version=user["session_version"],
                             expires_at=utcnow() + timedelta(seconds=ttl)).returning(AccountToken.id)).scalar()
    if not mail.queue_message(user["email"], purpose, raw, token_id):
        with db:
            db.execute(update(AccountToken).where(AccountToken.id == token_id).values(used_at=utcnow()))


def request_password_reset(email, client_ip):
    normalized = _email(email)
    retry = _budget("reset", normalized, client_ip)
    if retry:
        return retry
    # Recovery uses the stored account identity, including addresses accepted before
    # stricter signup validation. Do not change or revalidate those addresses here.
    lookup_safe = storable_text(email) and 1 <= len(email.strip()) <= 254
    user = get_db().execute(select(User).where(func.lower(User.email) == normalized, User.active == 1)).fetchone() if lookup_safe else None
    if user is not None:
        _issue(user, "reset")
    return 0


def send_verification(user_id, client_ip="local"):
    user = get_db().execute(select(User).where(User.id == user_id, User.active == 1)).fetchone()
    if user is None:
        return 0
    retry = _budget("verify", _email(user["email"]), client_ip)
    if retry:
        return retry
    if not user["email_verified"]:
        _issue(user, "verify")
    return 0


def invalidate_email_links(user_id):
    """Invalidate links in the transaction that holds and updates the user row."""
    get_db().execute(update(AccountToken).where(AccountToken.user_id == user_id, AccountToken.used_at.is_(None))
                     .values(used_at=utcnow()))


def email_changed(user_id, client_ip="local"):
    """Invalidate existing links and request verification, including in local mode."""
    db = get_db()
    with db:
        db.execute(update(User).where(User.id == user_id).values(email_verified=0))
        invalidate_email_links(user_id)
    return send_verification(user_id, client_ip)


def _valid_conditions(purpose, now):
    account = select(User.id).where(User.id == AccountToken.user_id, User.active == 1,
                                  User.email == AccountToken.email_snapshot,
                                  User.session_version == AccountToken.session_version)
    if purpose == "verify":
        account = account.where(User.email_verified == 0)
    return (AccountToken.purpose == purpose, AccountToken.used_at.is_(None),
            AccountToken.expires_at > now, account.exists())


def inspect_token(raw, purpose):
    token = get_db().execute(select(AccountToken.id).where(AccountToken.token_hash == _digest(raw),
                            *_valid_conditions(purpose, utcnow()))).fetchone()
    if token is None:
        raise InvalidAccountToken("Este link é inválido ou expirou.")


def _consume(raw, purpose, password=None):
    digest = _digest(raw)
    password_hash = generate_password_hash(password) if purpose == "reset" else None
    db = get_db()
    with db:
        owner_id = db.execute(select(AccountToken.user_id).where(AccountToken.token_hash == digest,
                              AccountToken.purpose == purpose)).scalar()
        if owner_id is None:
            raise InvalidAccountToken("Este link é inválido ou expirou.")
        # Lock the account before any token row. Different tokens for the same
        # account then serialize on both engines, including bulk invalidation.
        owner = db.execute(update(User).where(User.id == owner_id, User.active == 1)
                           .values(session_version=User.session_version).returning(User.id)).fetchone()
        if owner is None:
            raise InvalidAccountToken("Este link é inválido ou expirou.")
        now = utcnow()
        token = db.execute(update(AccountToken).where(AccountToken.token_hash == digest, *_valid_conditions(purpose, now))
                           .values(used_at=now).returning(AccountToken.user_id, AccountToken.email_snapshot,
                                                        AccountToken.session_version)).fetchone()
        if token is None:
            raise InvalidAccountToken("Este link é inválido ou expirou.")
        changed = db.execute(update(User).where(User.id == token["user_id"], User.active == 1,
                             User.email == token["email_snapshot"], User.session_version == token["session_version"])
                             .values(**({"senha": password_hash, "session_version": User.session_version + 1}
                                        if purpose == "reset" else {"email_verified": 1})))
        if changed.rowcount != 1:
            raise InvalidAccountToken("Este link é inválido ou expirou.")
        invalidated = update(AccountToken).where(AccountToken.user_id == token["user_id"], AccountToken.used_at.is_(None))
        if purpose == "verify":
            invalidated = invalidated.where(AccountToken.purpose == "verify")
        db.execute(invalidated.values(used_at=now))
    return token["user_id"]


def consume_reset(raw, password, confirmation):
    inspect_token(raw, "reset")
    if not isinstance(password, str) or not senha_forte(password):
        raise FormValidationError("senha", "Use 8 a 128 caracteres, com maiúscula, minúscula, número e !@#$%&_*." )
    if confirmation != password:
        raise FormValidationError("senha_confirmacao", "As senhas precisam ser iguais.")
    return _consume(raw, "reset", password)


def consume_verification(raw):
    return _consume(raw, "verify")
