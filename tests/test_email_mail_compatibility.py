"""Strict new addresses must not break the local spool or existing recovery."""
from criticard.accounts.mail import configured
from criticard.db import get_db
from criticard.validation import email_valido
from test_accounts import accounts_app, accounts_client, database, links, post


def test_local_file_mail_accepts_test_sender_but_smtp_does_not(accounts_app):
    with accounts_app.app_context():
        assert configured()
        accounts_app.config.update(ACCOUNT_MAIL_BACKEND="smtp", ACCOUNT_SMTP_HOST="smtp.example.com")
        assert not configured()


def test_file_mail_uses_a_valid_local_default_when_sender_is_blank(accounts_app):
    accounts_app.config["ACCOUNT_MAIL_FROM"] = ""
    with accounts_app.app_context():
        assert configured()


def test_recovery_accepts_an_existing_legacy_address_without_changing_it(accounts_app, accounts_client):
    with accounts_app.app_context():
        with get_db() as db:
            db.execute("UPDATE usuarios SET email=? WHERE id=1", ("old..address@example.com",))
    response = post(accounts_client, "/recuperar-senha", {"email": "old..address@example.com"}, json=True)
    assert response.status_code == 200
    assert len(links(accounts_app)) == 1
    assert database(accounts_app, "SELECT email FROM usuarios WHERE id=1")[0][0] == "old..address@example.com"
    assert not email_valido("old..address@example.com")


def test_public_registration_validation_rejects_reserved_test_domain():
    assert not email_valido("new-user@criticard.test")
