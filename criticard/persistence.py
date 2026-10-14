"""Context-scoped SQLAlchemy transactions and portable result records."""
import re

from flask import current_app, g
from sqlalchemy import text

# Register the additive preference table in the shared declarative metadata.
from .settings.models import UserSettings  # noqa: F401
from .progression.models import ProgressionProfile, ExperienceEvent, AchievementGrant, RewardGrant  # noqa: F401
from .communities.models import (Community, CommunityMembership, CommunityJoinRequest, CommunityInvite,
    CommunityPost, CommunityComment, CommunityReaction)  # noqa: F401
from .social.models import WorkFollow, CategoryFollow  # noqa: F401


class Record(dict):
    def __getitem__(self, key):
        return tuple(self.values())[key] if isinstance(key, (int, slice)) else super().__getitem__(key)


class Result:
    def __init__(self, result):
        self.result = result

    def fetchone(self):
        row = self.result.fetchone()
        return Record(row._mapping) if row is not None else None

    def fetchall(self):
        return [Record(row._mapping) for row in self.result.fetchall()]

    def scalar(self):
        return self.result.scalar()

    @property
    def rowcount(self):
        return self.result.rowcount


class Database:
    def __init__(self, engine):
        self.connection = engine.connect()

    @property
    def dialect(self):
        return self.connection.dialect.name

    def execute(self, statement, parameters=None):
        # Keep command-line/legacy test helpers usable while production uses
        # SQLAlchemy expressions. Do not rewrite quoted SQL literals.
        if isinstance(statement, str):
            if parameters is not None and not isinstance(parameters, dict):
                parameters = tuple(parameters)
                index = 0
                def bind(_match):
                    nonlocal index
                    name = f'p{index}'
                    index += 1
                    return ':' + name
                parts = re.split(r"('(?:''|[^'])*'|\"(?:\"\"|[^\"])*\")", statement)
                for i in range(0, len(parts), 2):
                    parts[i] = re.sub(r'\?', bind, parts[i])
                if index != len(parameters):
                    raise ValueError('SQL parameter count does not match placeholders')
                statement = ''.join(parts)
                parameters = {f'p{i}': value for i, value in enumerate(parameters)}
            statement = text(statement)
        return Result(self.connection.execute(statement, parameters or {}))

    def commit(self):
        self.connection.commit()

    def rollback(self):
        self.connection.rollback()

    def close(self):
        self.connection.close()

    def __enter__(self):
        return self

    def __exit__(self, error_type, error, traceback):
        self.rollback() if error_type else self.commit()


def get_engine():
    return current_app.extensions['database_engine']


def get_db():
    if 'database' not in g:
        g.database = Database(get_engine())
    return g.database


def close_db(error=None):
    database = g.pop('database', None)
    if database is not None:
        database.close()
