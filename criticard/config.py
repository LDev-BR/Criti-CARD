"""Environment configuration, independent of the current working directory."""
import os
import secrets
from pathlib import Path
from urllib.parse import urlsplit

from sqlalchemy.engine import make_url

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent


def defaults():
    load_dotenv(ROOT / ".env")
    config = {
        "SECRET_KEY": os.getenv("SECRET_KEY") or None,
        "DATABASE": os.getenv("DATABASE") or str(ROOT / "criticard.db"),
        "DATABASE_URL": os.getenv("DATABASE_URL") or None,
        "SESSION_COOKIE_SECURE": os.getenv("SESSION_COOKIE_SECURE", "0") == "1",
        "UPLOAD_FOLDER": os.getenv("UPLOAD_FOLDER") or str(ROOT / "static" / "uploads"),
        "CAPA_FOLDER": os.getenv("CAPA_FOLDER") or str(ROOT / "static" / "cards"),
        # The image limit is enforced in uploads.py; reserve space for form text
        # and the multipart envelope so an image at that limit can be sent.
        "MAX_CONTENT_LENGTH": 3 * 1024 * 1024 + 64 * 1024,
        "MAX_FORM_MEMORY_SIZE": 64 * 1024,
        "MAX_FORM_PARTS": 24,
        "LOGIN_ATTEMPT_LIMIT": 10,
        "LOGIN_ATTEMPT_WINDOW": 300,
        "REGISTER_ATTEMPT_LIMIT": 5,
        "REGISTER_ATTEMPT_WINDOW": 900,
        "SETTINGS_SECURITY_ATTEMPT_LIMIT": 10,
        "SETTINGS_SECURITY_ATTEMPT_WINDOW": 300,
        "PRIVACY_REQUEST_ATTEMPT_LIMIT": 10,
        "PRIVACY_REQUEST_ATTEMPT_WINDOW": 300,
        "PRIVACY_ADMIN_ATTEMPT_LIMIT": 30,
        "PRIVACY_ADMIN_ATTEMPT_WINDOW": 300,
        "COMMUNITY_WRITE_ATTEMPT_LIMIT": 20,
        "COMMUNITY_WRITE_ATTEMPT_WINDOW": 300,
        "SESSION_COOKIE_HTTPONLY": True,
        "SESSION_COOKIE_SAMESITE": "Lax",
        "HOST": os.getenv("HOST", "127.0.0.1"),
        "PORT": int(os.getenv("PORT", "5000")),
        "DEBUG": os.getenv("FLASK_DEBUG", "0") == "1",
        "ADM_USERNAME": os.getenv("ADM_USERNAME", ""),
        "ADM_SENHA": os.getenv("ADM_SENHA", ""),
        "ADM_EMAIL": os.getenv("ADM_EMAIL", "admin@example.com"),
    }
    for name, fallback in {
        'ENVIRONMENT': 'development', 'STORAGE_BACKEND': 'local',
        'S3_ENDPOINT_URL': '', 'S3_REGION': 'us-east-1', 'S3_BUCKET': '',
        'S3_ACCESS_KEY_ID': '', 'S3_SECRET_ACCESS_KEY': '', 'S3_PUBLIC_BASE_URL': '', 'S3_PREFIX': 'criticard',
        'ACCOUNT_MAIL_BACKEND': 'disabled', 'ACCOUNT_BASE_URL': '',
        'ACCOUNT_OUTBOX_PATH': str(ROOT / 'instance' / 'outbox'),
        'ACCOUNT_MAIL_FROM': '', 'ACCOUNT_SMTP_HOST': '', 'ACCOUNT_SMTP_USERNAME': '',
        'ACCOUNT_SMTP_PASSWORD': '', 'ACCOUNT_SMTP_TLS': 'starttls',
        'PRIVACY_CONTROLLER_NAME': 'Luis Duarte', 'PRIVACY_CONTACT_EMAIL': '',
    }.items():
        config[name] = os.getenv(name, fallback)
    for name, fallback in {'ACCOUNT_SMTP_PORT':587, 'PROXY_HOPS':0}.items():
        config[name] = int(os.getenv(name, str(fallback)))
    config['TRUSTED_HOSTS'] = [host.strip() for host in os.getenv('TRUSTED_HOSTS', '').split(',') if host.strip()] or None
    return config


def validate_runtime(app):
    config = app.config
    if not 0 <= config.get('PROXY_HOPS', 0) <= 3:
        raise ValueError('PROXY_HOPS deve indicar de zero a três proxies confiáveis.')
    if config.get('ENVIRONMENT') != 'production':
        return
    if not isinstance(config['SECRET_KEY'], str) or len(config['SECRET_KEY']) < 32:
        raise ValueError('Defina uma SECRET_KEY própria com pelo menos 32 caracteres para produção.')
    if not config.get('DATABASE_URL') or make_url(config['DATABASE_URL']).get_backend_name() not in ('postgresql', 'postgres'):
        raise ValueError('Configure DATABASE_URL com PostgreSQL para produção.')
    if config['DEBUG'] or not config['SESSION_COOKIE_SECURE'] or not config['TRUSTED_HOSTS']:
        raise ValueError('Produção requer DEBUG desativado, cookie seguro e TRUSTED_HOSTS explícitos.')
    base = urlsplit(config.get('ACCOUNT_BASE_URL', ''))
    if base.scheme != 'https' or not base.hostname or base.username or base.password or base.query or base.fragment:
        raise ValueError('Defina ACCOUNT_BASE_URL com a URL HTTPS pública.')
    if (config.get('ACCOUNT_MAIL_BACKEND') != 'smtp' or not config.get('ACCOUNT_SMTP_HOST')
            or not config.get('ACCOUNT_MAIL_FROM') or config.get('ACCOUNT_SMTP_TLS') not in ('starttls', 'ssl')):
        raise ValueError('Configure SMTP seguro e remetente para recuperação de contas em produção.')


def ensure_secret_key(app):
    if app.config["SECRET_KEY"]:
        return
    path = Path(app.instance_path) / "secret_key"
    try:
        with path.open("x", encoding="ascii") as file:
            file.write(secrets.token_hex(32))
    except FileExistsError:
        pass
    app.config["SECRET_KEY"] = path.read_text(encoding="ascii").strip()
