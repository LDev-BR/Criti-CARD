from datetime import datetime

from alembic import context
from sqlalchemy import DateTime, String, bindparam, event
from sqlalchemy.sql.elements import TextClause
from sqlalchemy.sql.sqltypes import NullType

from criticard.models import Base

connection = context.config.attributes['connection']


def typed_migration_parameters(connection, statement, multiparams, params, execution_options):
    """Supply missing types without rewriting previously applied revisions.

    A parameter reused by INSERT ... SELECT and a VARCHAR comparison can be
    inferred as both TEXT and VARCHAR by psycopg. Explicit types add the same
    cast at both occurrences. DateTime binds also use SQLAlchemy's timestamp
    processors instead of SQLite's deprecated default datetime adapter.
    """
    if isinstance(statement, TextClause):
        values = params or (multiparams[0] if multiparams else {})
        compiled = statement.compile()
        bindings = []
        for name, value in values.items():
            if name not in compiled.binds or not isinstance(compiled.binds[name].type, NullType):
                continue
            if isinstance(value, datetime):
                bindings.append(bindparam(name, type_=DateTime(timezone=True)))
            elif isinstance(value, str) and connection.dialect.name == 'postgresql':
                bindings.append(bindparam(name, type_=String()))
        if bindings:
            statement = statement.bindparams(*bindings)
    return statement, multiparams, params


event.listen(connection, 'before_execute', typed_migration_parameters, retval=True)
try:
    context.configure(connection=connection, target_metadata=Base.metadata,
                      render_as_batch=connection.dialect.name == 'sqlite', compare_type=True)
    with context.begin_transaction():
        context.run_migrations()
finally:
    event.remove(connection, 'before_execute', typed_migration_parameters)
