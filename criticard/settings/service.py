"""Validated, transactionally merged preference documents."""
from collections.abc import Mapping

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from ..persistence import get_db
from ..models import Category, User, utcnow
from ..validation import storable_text
from .models import UserSettings
from .schema import DEFAULTS, FIELDS, SECTION_FIELDS
from flask import g, has_request_context, session
from ..security import valid_session_identity


class SettingsError(ValueError):
    def __init__(self, message, field=None, status=400):
        super().__init__(message)
        self.field = field
        self.status = status


def _section(section):
    if not isinstance(section, str) or not SECTION_FIELDS.get(section):
        raise SettingsError('Área de preferências não encontrada.', status=404)


def _user_id(user_id):
    if type(user_id) is not int or not 1 <= user_id <= 2**63 - 1:
        raise SettingsError('Conta não encontrada.', status=404)


def get_preferences(user_id):
    """Return fresh defaults plus stored values, without writing on reads."""
    _user_id(user_id)
    stored = get_db().execute(select(UserSettings.preferences).where(UserSettings.user_id == user_id)).scalar()
    return {**DEFAULTS, **{key: value for key, value in (stored or {}).items() if key in DEFAULTS}}


def _validate(section, data):
    _section(section)
    if not isinstance(data, Mapping):
        raise SettingsError('Envie um objeto com os campos desta área.')
    unknown = set(data) - set(SECTION_FIELDS[section])
    if unknown:
        raise SettingsError('Este campo não pertence à área selecionada.', field=next(iter(unknown)))
    result = {}
    for name, value in data.items():
        field = FIELDS[name]
        if field['kind'] == 'boolean':
            valid = type(value) is bool
        elif field['kind'] == 'integer':
            valid = type(value) is int and 0 <= value <= 100
        elif name == 'feed_category':
            valid = storable_text(value) and (value == '' or get_db().execute(
                select(Category.id).where(Category.slug == value)).scalar() is not None)
        elif name.startswith('progression_'):
            from ..progression.catalog import reward_spec
            spec = reward_spec(value)
            expected_kind = name.removeprefix('progression_')
            valid = isinstance(value,str) and ((name=='progression_badge' and value=='') or
                (spec is not None and spec['kind']==expected_kind))
        else:
            valid = isinstance(value, str) and value in field['choices']
        if not valid:
            raise SettingsError('Escolha um valor válido para esta opção.', field=name)
        result[name] = value
    return result


def save_preferences(user_id, section, data):
    _user_id(user_id)
    _section(section)
    db = get_db()
    with db:
        # Use the same owner serialization point as social/chat privacy checks.
        # SQLite must reserve its writer before reading the existing document.
        if db.dialect == 'sqlite':
            owner = db.execute(update(User).where(User.id == user_id)
                .values(session_version=User.session_version).returning(User.id)).scalar()
        else:
            owner = db.execute(select(User.id).where(User.id == user_id).with_for_update()).scalar()
        if owner is None:
            raise SettingsError('Conta não encontrada.', status=404)
        values = _validate(section, data)
        if section=='jornada':
            from ..progression.queries import owned_rewards
            owner_row = db.execute(select(User).where(User.id==user_id)).fetchone()
            if not owner_row['active'] or (has_request_context() and g.user and
                not valid_session_identity(owner_row,session)):
                raise SettingsError('Sua sessão expirou. Entre novamente.',status=401)
            owned = owned_rewards(user_id)
            for field,value in values.items():
                if field in ('progression_title','progression_frame','progression_card','progression_badge') and value and value not in owned:
                    raise SettingsError('Esta recompensa ainda está bloqueada.',field=field)
        preferences = {**get_preferences(user_id), **values}
        dialect_insert = pg_insert if db.dialect == 'postgresql' else sqlite_insert
        statement = dialect_insert(UserSettings).values(user_id=user_id, preferences=preferences, updated_at=utcnow())
        db.execute(statement.on_conflict_do_update(index_elements=['user_id'], set_={
            'preferences': statement.excluded.preferences, 'updated_at': statement.excluded.updated_at}))
    return preferences


def reset_preferences(user_id, section):
    _section(section)
    return save_preferences(user_id, section, {name: DEFAULTS[name] for name in SECTION_FIELDS[section]})
