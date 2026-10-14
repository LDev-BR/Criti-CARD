"""Form normalization and domain validation shared by registration and editing."""
import re

from email_validator import EmailNotValidError, validate_email


class FormValidationError(ValueError):
    """A readable validation message associated with one form control."""

    def __init__(self, field, message):
        super().__init__(message)
        self.field = field


def storable_text(value):
    """SQLite/PostgreSQL text must be valid UTF-8 without a NUL character."""
    if not isinstance(value, str) or '\0' in value:
        return False
    try:
        value.encode('utf-8')
    except UnicodeEncodeError:
        return False
    return True


def username_valido(username):
    return storable_text(username) and re.fullmatch(r"[a-zA-Z0-9_-]{3,15}", username) is not None


def email_valido(email, *, test_environment=False):
    if not storable_text(email) or len(email) > 254:
        return False
    try:
        validate_email(email, check_deliverability=False, allow_smtputf8=False, test_environment=test_environment)
    except EmailNotValidError:
        return False
    return True


def senha_forte(senha):
    return (storable_text(senha) and 8 <= len(senha) <= 128 and any(c.islower() for c in senha)
            and any(c.isupper() for c in senha) and any(c.isdigit() for c in senha)
            and any(c in "!@#$%&_*" for c in senha))


def profile_values(form):
    values = {key: form.get(key, "").strip() for key in ("username", "nome", "apelido", "about", "email")}
    values["username"] = values["username"].upper()
    values["email"] = values["email"].lower()
    return values


def validate_profile(values, *, existing_email=None):
    if not username_valido(values["username"]):
        raise FormValidationError("username", "Username: use de 3 a 15 letras, números, hífen ou sublinhado.")
    # Public identity can be a username; additional profile details are optional.
    values["nome"] = values["nome"] or values["username"]
    for key, limit, label in (("nome", 80, "Nome público"), ("apelido", 40, "Apelido"), ("about", 2000, "Biografia")):
        if not storable_text(values[key]) or len(values[key]) > limit:
            raise FormValidationError(key, f"{label}: use até {limit} caracteres.")
    # Changing other profile details must not force replacement of a legacy address.
    unchanged_email = (existing_email is not None and storable_text(existing_email)
                       and values["email"].lower() == existing_email.lower())
    if not unchanged_email and not email_valido(values["email"]):
        raise FormValidationError("email", "Informe um email válido.")
    if unchanged_email:
        values["email"] = existing_email


def validate_card(form):
    title = form.get("titulo", "").strip()
    description = form.get("sobre", "").strip()
    if not storable_text(title) or not 1 <= len(title) <= 120:
        raise FormValidationError("titulo", "Título: preencha entre 1 e 120 caracteres.")
    if not storable_text(description) or not 1 <= len(description) <= 3000:
        raise FormValidationError("sobre", "Crítica: preencha entre 1 e 3000 caracteres.")
    try:
        score = int(form.get("nota", ""))
    except (ValueError, TypeError):
        raise FormValidationError("nota", "A nota deve ser um número inteiro de 0 a 100.") from None
    if not 0 <= score <= 100:
        raise FormValidationError("nota", "A nota deve estar entre 0 e 100.")
    return title, description, score
