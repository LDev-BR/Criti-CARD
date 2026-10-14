"""Recovery and verification links are private, expiring and single-use."""
import hashlib
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier

import pytest
from sqlalchemy import insert, select
from werkzeug.security import check_password_hash, generate_password_hash

from criticard import create_app
from criticard.db import get_db
from criticard.models import User


@pytest.fixture
def accounts_app(tmp_path):
    app = create_app({
        "TESTING": True, "SECRET_KEY": "accounts-test-key", "DATABASE": str(tmp_path / "accounts.db"),
        "UPLOAD_FOLDER": str(tmp_path / "avatars"), "CAPA_FOLDER": str(tmp_path / "covers"),
        "ADM_USERNAME": "", "ADM_SENHA": "", "ACCOUNT_MAIL_BACKEND": "file",
        "ACCOUNT_BASE_URL": "http://localhost", "ACCOUNT_OUTBOX_PATH": str(tmp_path / "outbox"),
        "ACCOUNT_MAIL_FROM": "no-reply@criticard.test", "RESET_IP_LIMIT": 30, "RESET_EMAIL_LIMIT": 20,
        "VERIFY_IP_LIMIT": 30, "VERIFY_EMAIL_LIMIT": 20,
    })
    with app.app_context():
        db = get_db()
        with db:
            for name in ("ALICE", "BOB"):
                db.execute(insert(User).values(username=name, nome=name.title(), apelido="Leitor", about="Minha conta",
                           email=name.lower() + "@example.com", senha=generate_password_hash("Password1!")))
    yield app


@pytest.fixture
def accounts_client(accounts_app):
    return accounts_app.test_client()


def post(client, path, data=None, *, json=False):
    page = client.get("/recuperar-senha")
    token = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
    headers = {"X-CSRF-Token": token.group(1)} if token else {}
    return client.post(path, **({"json": data or {}} if json else {"data": data or {}}), headers=headers)


def database(app, statement, params=()):
    with app.app_context():
        return get_db().execute(statement, params).fetchall()


def links(app, purpose="redefinir-senha"):
    from pathlib import Path
    results = []
    for path in sorted(Path(app.config["ACCOUNT_OUTBOX_PATH"]).glob("*.eml")):
        match = re.search(r"/" + purpose + r"/([A-Za-z0-9_-]{43})", path.read_text(encoding="utf-8"))
        if match:
            results.append("/" + purpose + "/" + match.group(1))
    return results


def reset_request(client):
    return post(client, "/recuperar-senha", {"email": "alice@example.com"})


def sign_in(client, user=1):
    from criticard.security import session_identity
    with client.application.app_context():
        record = get_db().execute(select(User).where(User.id == user)).fetchone()
        stamp = session_identity(record)
    with client.session_transaction() as session:
        session["usuario_id"] = user
        session["session_version"] = record["session_version"]
        session["auth_stamp"] = stamp


def reset_password(client, path, password="Different2!"):
    return post(client, path, {"senha": password, "senha_confirmacao": password})


def test_recovery_form_is_public_and_does_not_require_a_session(accounts_client):
    response = accounts_client.get("/recuperar-senha")
    assert response.status_code == 200
    assert 'name="email"' in response.text and 'name="csrf_token"' in response.text


def test_unknown_email_has_identical_public_response_and_creates_no_token(accounts_client, accounts_app):
    known = post(accounts_client, "/recuperar-senha", {"email": "alice@example.com"}, json=True)
    unknown = post(accounts_client, "/recuperar-senha", {"email": "nobody@example.com"}, json=True)
    assert known.status_code == unknown.status_code == 200
    assert known.json == unknown.json
    assert len(links(accounts_app)) == 1
    assert database(accounts_app, "SELECT COUNT(*) FROM account_tokens")[0][0] == 1


def test_reset_token_is_hashed_and_opening_link_does_not_consume_it(accounts_client, accounts_app):
    reset_request(accounts_client)
    path = links(accounts_app)[0]
    digest = hashlib.sha256(path.rsplit("/", 1)[1].encode()).hexdigest()
    token = database(accounts_app, "SELECT * FROM account_tokens")[0]
    assert token["token_hash"] == digest
    assert token["purpose"] == "reset" and token["email_snapshot"] == "alice@example.com"
    assert token["session_version"] == 0 and token["used_at"] is None
    assert accounts_client.get(path).status_code == 200
    assert accounts_client.get(path).headers["Referrer-Policy"] == "no-referrer"
    assert database(accounts_app, "SELECT used_at FROM account_tokens")[0][0] is None


def test_valid_reset_changes_password_once_and_revokes_existing_session(accounts_client, accounts_app):
    active = accounts_app.test_client()
    sign_in(active)
    reset_request(accounts_client)
    path = links(accounts_app)[0]
    assert reset_password(accounts_client, path).status_code == 302
    user = database(accounts_app, "SELECT senha,session_version FROM usuarios WHERE id=1")[0]
    assert check_password_hash(user["senha"], "Different2!")
    assert user["session_version"] == 1
    assert active.get("/backlog").status_code == 302
    assert reset_password(accounts_client, path).status_code == 400
    assert user["session_version"] == database(accounts_app, "SELECT session_version FROM usuarios WHERE id=1")[0][0]


def test_reset_invalidates_other_outstanding_links(accounts_client, accounts_app):
    reset_request(accounts_client)
    reset_request(accounts_client)
    first, second = links(accounts_app)
    assert reset_password(accounts_client, first).status_code == 302
    assert reset_password(accounts_client, second).status_code == 400


@pytest.mark.parametrize("password", ["short", "lowercase1!", "UPPERCASE1!", "NoDigits!!", "NoSymbol12", "A1!" + "x" * 126])
def test_invalid_password_does_not_consume_link(accounts_client, accounts_app, password):
    reset_request(accounts_client)
    path = links(accounts_app)[0]
    response = reset_password(accounts_client, path, password)
    assert response.status_code == 422 and 'id="senha-error"' in response.text
    assert database(accounts_app, "SELECT used_at FROM account_tokens")[0][0] is None
    assert reset_password(accounts_client, path).status_code == 302


def test_confirmation_must_match_before_consuming_link(accounts_client, accounts_app):
    reset_request(accounts_client)
    path = links(accounts_app)[0]
    assert post(accounts_client, path, {"senha": "Different2!", "senha_confirmacao": "Other2!"}).status_code == 422
    assert database(accounts_app, "SELECT used_at FROM account_tokens")[0][0] is None


@pytest.mark.parametrize("change", ["expires", "email", "session", "inactive"])
def test_expiry_or_changed_account_invalidates_reset(accounts_client, accounts_app, change):
    reset_request(accounts_client)
    path = links(accounts_app)[0]
    with accounts_app.app_context():
        db = get_db()
        with db:
            if change == "expires":
                db.execute("UPDATE account_tokens SET expires_at=?", ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(" "),))
            elif change == "email":
                db.execute("UPDATE usuarios SET email='new@example.com' WHERE id=1")
            elif change == "session":
                db.execute("UPDATE usuarios SET session_version=1 WHERE id=1")
            else:
                db.execute("UPDATE usuarios SET active=0 WHERE id=1")
    assert accounts_client.get(path).status_code == 400
    assert reset_password(accounts_client, path).status_code == 400
    assert check_password_hash(database(accounts_app, "SELECT senha FROM usuarios WHERE id=1")[0][0], "Password1!")


def test_verification_requires_post_and_is_single_use(accounts_client, accounts_app):
    sign_in(accounts_client)
    assert post(accounts_client, "/reenviar-verificacao").status_code == 200
    path = links(accounts_app, "verificar-email")[0]
    assert accounts_client.get(path).status_code == 200
    assert database(accounts_app, "SELECT email_verified FROM usuarios WHERE id=1")[0][0] == 0
    assert post(accounts_client, path).status_code == 200
    assert database(accounts_app, "SELECT email_verified FROM usuarios WHERE id=1")[0][0] == 1
    assert post(accounts_client, path).status_code == 400


def test_changed_email_cannot_be_verified_by_old_link(accounts_client, accounts_app):
    sign_in(accounts_client)
    post(accounts_client, "/reenviar-verificacao")
    path = links(accounts_app, "verificar-email")[0]
    with accounts_app.app_context():
        db = get_db()
        with db:
            db.execute("UPDATE usuarios SET email='new@example.com' WHERE id=1")
    assert post(accounts_client, path).status_code == 400
    assert database(accounts_app, "SELECT email_verified FROM usuarios WHERE id=1")[0][0] == 0


def test_token_purpose_cannot_be_swapped(accounts_client, accounts_app):
    reset_request(accounts_client)
    reset = links(accounts_app)[0]
    assert post(accounts_client, reset.replace("redefinir-senha", "verificar-email")).status_code == 400
    sign_in(accounts_client)
    post(accounts_client, "/reenviar-verificacao")
    verify = links(accounts_app, "verificar-email")[0]
    assert reset_password(accounts_client, verify.replace("verificar-email", "redefinir-senha")).status_code == 400


@pytest.mark.parametrize("email", ["alice@example.com", "nobody@example.com"])
def test_reset_rate_limits_ip_and_destination_without_enumeration(accounts_client, accounts_app, email):
    accounts_app.config.update(RESET_IP_LIMIT=10, RESET_EMAIL_LIMIT=1)
    assert post(accounts_client, "/recuperar-senha", {"email": email}, json=True).status_code == 200
    throttled = post(accounts_client, "/recuperar-senha", {"email": email}, json=True)
    assert throttled.status_code == 429 and int(throttled.headers["Retry-After"]) > 0
    assert post(accounts_client, "/recuperar-senha", {"email": "second@example.com"}, json=True).status_code == 200
    accounts_app.config["RESET_IP_LIMIT"] = 3
    assert post(accounts_client, "/recuperar-senha", {"email": "third@example.com"}, json=True).status_code == 429


def test_mail_disabled_and_host_header_do_not_leak_or_send_link(accounts_client, accounts_app):
    accounts_app.config["ACCOUNT_MAIL_BACKEND"] = "disabled"
    assert reset_request(accounts_client).status_code == 200
    assert links(accounts_app) == []
    accounts_app.config["ACCOUNT_MAIL_BACKEND"] = "file"
    page = accounts_client.get("/recuperar-senha", headers={"Host": "evil.example"})
    csrf = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
    assert accounts_client.post("/recuperar-senha", data={"email": "alice@example.com", "csrf_token": csrf},
                                headers={"Host": "evil.example"}).status_code == 200
    from pathlib import Path
    message = next(Path(accounts_app.config["ACCOUNT_OUTBOX_PATH"]).glob("*.eml")).read_text(encoding="utf-8")
    assert "http://localhost/redefinir-senha/" in message
    assert "evil.example" not in message


def test_recovery_and_resend_require_csrf_and_resend_requires_login(accounts_client, accounts_app):
    assert accounts_client.post("/recuperar-senha", data={"email": "alice@example.com"}).status_code == 400
    assert post(accounts_client, "/reenviar-verificacao", json=True).status_code == 401
    assert database(accounts_app, "SELECT COUNT(*) FROM account_tokens")[0][0] == 0


def test_simultaneous_reset_can_only_consume_once(accounts_client, accounts_app):
    reset_request(accounts_client)
    path = links(accounts_app)[0]
    gate = Barrier(2)

    def request_reset(_):
        client = accounts_app.test_client()
        with client.session_transaction() as session:
            session["csrf_token"] = "concurrent-accounts-csrf"
        gate.wait(timeout=10)
        return client.post(path, data={"senha": "Different2!", "senha_confirmacao": "Different2!"},
                           headers={"X-CSRF-Token": "concurrent-accounts-csrf"}).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(request_reset, range(2))) == [302, 400]
    assert database(accounts_app, "SELECT session_version FROM usuarios WHERE id=1")[0][0] == 1


def test_profile_email_hook_invalidates_links_and_marks_email_unverified(accounts_client, accounts_app):
    reset_request(accounts_client)
    old_link = links(accounts_app)[0]
    with accounts_app.app_context():
        db = get_db()
        with db:
            db.execute("UPDATE usuarios SET email='new@example.com',email_verified=1 WHERE id=1")
        from criticard.accounts.service import email_changed
        assert email_changed(1, "127.0.0.1") == 0
    assert database(accounts_app, "SELECT email_verified FROM usuarios WHERE id=1")[0][0] == 0
    assert len(links(accounts_app, "verificar-email")) == 1
    with accounts_app.app_context():
        db = get_db()
        with db:
            db.execute("UPDATE usuarios SET email='alice@example.com' WHERE id=1")
    assert reset_password(accounts_client, old_link).status_code == 400


def smtp_configuration(app):
    app.config.update(ACCOUNT_MAIL_BACKEND="smtp", ACCOUNT_BASE_URL="https://criticard.example",
                      ACCOUNT_MAIL_FROM="no-reply@criticard.example", ACCOUNT_SMTP_HOST="smtp.example")


def test_smtp_is_outside_http_and_failed_queue_delivery_remains_retryable(accounts_client, accounts_app, monkeypatch):
    from pathlib import Path
    from criticard.accounts import mail
    smtp_configuration(accounts_app)

    def fail_transport(message):
        raise OSError("Controlled transport failure")

    monkeypatch.setattr(mail, "_smtp_deliver", fail_transport)
    assert reset_request(accounts_client).status_code == 200
    outbox = Path(accounts_app.config["ACCOUNT_OUTBOX_PATH"])
    assert len(list(outbox.glob("*.eml"))) == 1
    with accounts_app.app_context():
        assert mail.send_pending() == {"sent": 0, "failed": 1, "discarded": 0}
    assert len(list(outbox.glob("*.eml"))) == 1
    assert list(outbox.glob("*.sending")) == []
    monkeypatch.setattr(mail, "_smtp_deliver", lambda message: None)
    with accounts_app.app_context():
        assert mail.send_pending() == {"sent": 1, "failed": 0, "discarded": 0}
        assert mail.send_pending() == {"sent": 0, "failed": 0, "discarded": 0}
    assert list(outbox.glob("*.eml")) == []
    assert len(list((outbox / "sent").glob("*.eml"))) == 1


def test_expired_spooled_email_is_discarded_without_delivery(accounts_client, accounts_app, monkeypatch):
    from pathlib import Path
    from criticard.accounts import mail
    smtp_configuration(accounts_app)
    reset_request(accounts_client)
    with accounts_app.app_context():
        db = get_db()
        with db:
            db.execute("UPDATE account_tokens SET used_at=?", (datetime.now(timezone.utc).isoformat(" "),))

    def forbidden_delivery(message):
        pytest.fail("An already consumed token was delivered")

    monkeypatch.setattr(mail, "_smtp_deliver", forbidden_delivery)
    with accounts_app.app_context():
        assert mail.send_pending() == {"sent": 0, "failed": 0, "discarded": 1}
    outbox = Path(accounts_app.config["ACCOUNT_OUTBOX_PATH"])
    assert len(list((outbox / "discarded").glob("*.eml"))) == 1


def test_spool_cannot_be_public_and_tokens_are_redacted_from_access_logs(accounts_client, accounts_app, caplog):
    import logging
    reset_request(accounts_client)
    path = links(accounts_app)[0]
    with caplog.at_level(logging.INFO, logger="werkzeug"):
        logging.getLogger("werkzeug").info('"%s" %s', "GET " + path + " HTTP/1.1", 200)
    assert "[redacted]" in caplog.text
    assert path.rsplit("/", 1)[1] not in caplog.text
    accounts_app.config["ACCOUNT_OUTBOX_PATH"] = accounts_app.static_folder + "/outbox"
    assert reset_request(accounts_client).status_code == 200
    assert database(accounts_app, "SELECT COUNT(*) FROM account_tokens")[0][0] == 1


def test_mail_batch_stops_after_current_delivery(accounts_client, accounts_app, monkeypatch):
    from pathlib import Path
    from threading import Event
    from criticard.accounts import mail
    smtp_configuration(accounts_app)
    for _ in range(3):
        reset_request(accounts_client)
    stop = Event()
    monkeypatch.setattr(mail, "_smtp_deliver", lambda message: stop.set())
    with accounts_app.app_context():
        assert mail.send_pending(stop_event=stop) == {"sent": 1, "failed": 0, "discarded": 0}
    assert len(list(Path(accounts_app.config["ACCOUNT_OUTBOX_PATH"]).glob("*.eml"))) == 2


def test_stale_worker_claim_uses_claim_timestamp_not_enqueue_time(accounts_client, accounts_app, monkeypatch):
    import time
    from pathlib import Path
    from criticard.accounts import mail
    smtp_configuration(accounts_app)
    reset_request(accounts_client)
    outbox = Path(accounts_app.config["ACCOUNT_OUTBOX_PATH"])
    pending = next(outbox.glob("*.eml"))
    old_timestamp = time.time_ns() - 901 * 10**9
    pending.replace(outbox / (pending.stem + "." + str(old_timestamp) + ".sending"))
    monkeypatch.setattr(mail, "_smtp_deliver", lambda message: None)
    with accounts_app.app_context():
        assert mail.send_pending() == {"sent": 1, "failed": 0, "discarded": 0}
    assert list(outbox.glob("*.sending")) == []
