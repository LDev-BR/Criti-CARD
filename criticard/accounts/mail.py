"""Private mail spool; SMTP delivery is an explicit operation outside HTTP."""
import os
import smtplib
import ssl
import time
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from flask import current_app

from criticard.validation import email_valido


class MailConfigurationError(ValueError):
    pass


def _settings():
    config = current_app.config
    backend = config.get("ACCOUNT_MAIL_BACKEND", "disabled")
    if backend == "disabled":
        return None
    if backend not in ("file", "smtp"):
        raise MailConfigurationError("Configure um transporte de email válido.")
    base = config.get("ACCOUNT_BASE_URL", "")
    parsed = urlsplit(base)
    local = parsed.hostname in ("localhost", "127.0.0.1", "::1")
    if (parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment or (parsed.scheme != "https" and not local)):
        raise MailConfigurationError("Configure a URL pública do aplicativo.")
    if backend == "file" and not local:
        raise MailConfigurationError("A caixa de saída local só pode ser usada em um ambiente local.")
    destination = Path(config.get("ACCOUNT_OUTBOX_PATH") or Path(current_app.instance_path) / "outbox").resolve()
    if destination.is_relative_to(Path(current_app.static_folder).resolve()):
        raise MailConfigurationError("A caixa de saída precisa ficar fora dos arquivos públicos.")
    sender = config.get("ACCOUNT_MAIL_FROM") or ("no-reply@criticard.test" if backend == "file" else "")
    if not isinstance(sender, str) or not email_valido(sender, test_environment=backend == "file"):
        raise MailConfigurationError("Configure o remetente dos emails de conta.")
    if backend == "smtp" and (not config.get("ACCOUNT_SMTP_HOST") or config.get("ACCOUNT_SMTP_TLS", "starttls") not in ("starttls", "ssl")):
        raise MailConfigurationError("Configure o servidor SMTP com transporte seguro.")
    return {"backend": backend, "base": base.rstrip("/"), "outbox": destination, "sender": sender}


def configured():
    try:
        return _settings() is not None
    except (ValueError, TypeError, OSError):
        current_app.logger.warning("O envio de emails de conta não está configurado corretamente.")
        return False


def _private_directory(path):
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name != "nt":
        path.chmod(0o700)


def queue_message(recipient, purpose, token, token_id):
    try:
        settings = _settings()
        if settings is None:
            return False
        path = "/redefinir-senha/" if purpose == "reset" else "/verificar-email/"
        subject = "Redefinir sua senha" if purpose == "reset" else "Verificar seu email"
        instruction = "Escolha uma nova senha" if purpose == "reset" else "Confirme seu email"
        message = EmailMessage(policy=policy.SMTPUTF8)
        message["From"] = settings["sender"]
        message["To"] = recipient
        message["Subject"] = subject + " · Criti-CARD"
        message["X-CritiCARD-Token-ID"] = str(token_id)
        message["X-CritiCARD-Purpose"] = purpose
        message.set_content(instruction + " pelo link abaixo:\n\n" + settings["base"] + path + token
                            + "\n\nEste link expira e só pode ser utilizado uma vez."
                            + "\nSe você não pediu esta mensagem, pode ignorá-la.\n", cte="8bit")
        _private_directory(settings["outbox"])
        final = settings["outbox"] / (uuid4().hex + ".eml")
        staging = final.with_suffix(".writing")
        descriptor = os.open(staging, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(message.as_bytes())
            stream.flush()
            os.fsync(stream.fileno())
        staging.replace(final)
        return True
    except (ValueError, TypeError, OSError):
        current_app.logger.warning("Não foi possível preparar o email da conta.")
        return False


def _smtp_deliver(message):
    config = current_app.config
    tls = config.get("ACCOUNT_SMTP_TLS", "starttls")
    host = config["ACCOUNT_SMTP_HOST"]
    port = int(config.get("ACCOUNT_SMTP_PORT") or (465 if tls == "ssl" else 587))
    context = ssl.create_default_context()
    connection = (smtplib.SMTP_SSL(host, port, timeout=10, context=context) if tls == "ssl"
                  else smtplib.SMTP(host, port, timeout=10))
    with connection as smtp:
        if tls == "starttls":
            smtp.ehlo()
            smtp.starttls(context=context)
            smtp.ehlo()
        username = config.get("ACCOUNT_SMTP_USERNAME")
        if username:
            smtp.login(username, config.get("ACCOUNT_SMTP_PASSWORD", ""))
        smtp.send_message(message)


def _pending_token(token_id, purpose):
    from sqlalchemy import select
    from criticard.db import get_db
    from .models import AccountToken
    from .service import _valid_conditions
    from criticard.models import utcnow
    if not 1 <= token_id <= 2**63 - 1 or purpose not in ("reset", "verify"):
        return False
    return get_db().execute(select(AccountToken.id).where(AccountToken.id == token_id,
                           *_valid_conditions(purpose, utcnow()))).fetchone() is not None


def send_pending(limit=50, stop_event=None):
    """Claim pending files atomically. A failed delivery remains retryable."""
    settings = _settings()
    if settings is None or settings["backend"] != "smtp":
        raise MailConfigurationError("Configure ACCOUNT_MAIL_BACKEND=smtp antes de enviar emails.")
    outbox = settings["outbox"]
    _private_directory(outbox)
    result = {"sent": 0, "failed": 0, "discarded": 0}
    # Recover a crashed worker only after its SMTP timeout has elapsed.
    for claimed in outbox.glob("*.sending"):
        try:
            job_id, stamp = claimed.stem.rsplit(".", 1)
            if time.time() - int(stamp) / 10**9 > 600:
                claimed.replace(outbox / (job_id + ".eml"))
        except (FileNotFoundError, ValueError):
            pass
    for pending in sorted(outbox.glob("*.eml"))[:limit]:
        if stop_event is not None and stop_event.is_set():
            break
        claimed = outbox / (pending.stem + "." + str(time.time_ns()) + ".sending")
        try:
            pending.replace(claimed)
        except FileNotFoundError:
            continue
        try:
            message = BytesParser(policy=policy.SMTPUTF8).parsebytes(claimed.read_bytes())
            token_id = int(message.get("X-CritiCARD-Token-ID", "0"))
            purpose = message.get("X-CritiCARD-Purpose", "")
            if not _pending_token(token_id, purpose):
                archive = outbox / "discarded"
                _private_directory(archive)
                claimed.replace(archive / pending.name)
                result["discarded"] += 1
                continue
            _smtp_deliver(message)
            archive = outbox / "sent"
            _private_directory(archive)
            claimed.replace(archive / pending.name)
            result["sent"] += 1
        except (ValueError, OSError, smtplib.SMTPException):
            if claimed.exists():
                claimed.replace(pending)
            result["failed"] += 1
            current_app.logger.warning("A entrega de um email da conta falhou; ele permanece na fila.")
    return result
