"""Recovery and verification forms with no account enumeration."""
import logging
import re

import click
from flask import Blueprint, flash, g, jsonify, redirect, render_template, request, session, url_for

from criticard.security import login_required, wants_json
from criticard.validation import FormValidationError
from . import service
from .mail import MailConfigurationError, send_pending

bp = Blueprint("accounts", __name__, cli_group=None)
_TOKEN_PATH = re.compile(r"(/(?:redefinir-senha|verificar-email)/)[^/?\s\"]+")


class AccountTokenLogFilter(logging.Filter):
    def filter(self, record):
        def redact(value):
            return _TOKEN_PATH.sub(r"\1[redacted]", value) if isinstance(value, str) else value
        record.msg = redact(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(redact(value) for value in record.args)
        elif isinstance(record.args, dict):
            record.args = {key: redact(value) for key, value in record.args.items()}
        return True


@bp.record_once
def register_account_security(state):
    for name in ("werkzeug", "gunicorn.access"):
        logger = logging.getLogger(name)
        if not any(isinstance(item, AccountTokenLogFilter) for item in logger.filters):
            logger.addFilter(AccountTokenLogFilter())


@bp.after_request
def protect_account_response(response):
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store"
    return response


def _payload():
    data = request.get_json(silent=True) if request.is_json else request.form
    return data if hasattr(data, "get") else {}


def _generic(message, template, retry=0):
    response = jsonify(message=message) if wants_json() else render_template(template, submitted=True, message=message)
    return response, 429 if retry else 200, {"Retry-After": str(retry)} if retry else {}


@bp.route("/recuperar-senha", methods=["GET", "POST"])
def forgot():
    if request.method == "POST":
        retry = service.request_password_reset(_payload().get("email", ""), request.remote_addr)
        return _generic(service.RECOVERY_MESSAGE, "accounts/forgot.html", retry)
    return render_template("accounts/forgot.html", submitted=False)


def _invalid_link(purpose):
    if wants_json():
        return jsonify(error="Este link é inválido ou expirou."), 400
    return render_template("accounts/invalid.html", purpose=purpose), 400


@bp.route("/redefinir-senha/<token>", methods=["GET", "POST"])
def reset(token):
    field_errors = {}
    try:
        if request.method == "POST":
            payload = _payload()
            service.consume_reset(token, payload.get("senha", ""), payload.get("senha_confirmacao", ""))
            session.clear()
            flash("Senha alterada. Entre novamente com sua nova senha.", "success")
            if wants_json():
                return jsonify(message="Senha alterada. Entre novamente com sua nova senha.")
            return redirect(url_for("auth.index"))
        service.inspect_token(token, "reset")
    except service.InvalidAccountToken:
        return _invalid_link("reset")
    except FormValidationError as error:
        if wants_json():
            return jsonify(error=str(error), field=error.field), 422
        field_errors[error.field] = str(error)
    return render_template("accounts/reset.html", field_errors=field_errors), 422 if field_errors else 200


@bp.route("/verificar-email/<token>", methods=["GET", "POST"])
def verify(token):
    try:
        if request.method == "POST":
            service.consume_verification(token)
            if wants_json():
                return jsonify(message="Email verificado. Sua conta está pronta.")
            return render_template("accounts/result.html", message="Email verificado. Sua conta está pronta.")
        service.inspect_token(token, "verify")
    except service.InvalidAccountToken:
        return _invalid_link("verify")
    return render_template("accounts/verify.html")


@bp.post("/reenviar-verificacao")
@login_required
def resend():
    retry = service.send_verification(g.user["id"], request.remote_addr)
    return _generic(service.VERIFICATION_MESSAGE, "accounts/result.html", retry)


@bp.cli.command("accounts-send-mail")
@click.option("--limit", type=click.IntRange(1, 1000), default=50)
def send_mail_command(limit):
    """Send pending private account mail through the explicitly configured SMTP."""
    try:
        result = send_pending(limit)
    except MailConfigurationError as error:
        raise click.ClickException(str(error)) from None
    click.echo(f"Emails enviados: {result['sent']}; pendentes após falha: {result['failed']}; links expirados: {result['discarded']}.")
