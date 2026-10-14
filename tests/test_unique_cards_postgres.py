"""Real PostgreSQL enforces review uniqueness under concurrent publication."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import insert, select, update
from sqlalchemy.exc import IntegrityError

from criticard.db import get_db
from criticard.models import Card, User
from criticard.security import session_identity
from conftest import post
from test_postgres import pg_app, pg_database_url  # noqa: F401


def test_concurrent_publications_create_only_one_review(pg_app):
    with pg_app.app_context():
        user = get_db().execute(select(User).where(User.id == 1)).fetchone()
        stamp = session_identity(user)
    simultaneous = Barrier(5)
    def publish(number):
        client = pg_app.test_client()
        with client.session_transaction() as session:
            session.update(usuario_id=1, session_version=user['session_version'], auth_stamp=stamp)
        simultaneous.wait(timeout=10)
        return post(client, '/cadastro_cards', {'obra_id':'1', 'sobre':f'Crítica {number}', 'nota':'90'})
    with ThreadPoolExecutor(max_workers=5) as pool:
        responses = list(pool.map(publish, range(5)))
    assert sum(response.status_code == 302 for response in responses) == 1
    assert sum(response.status_code == 200 and 'obra_id-error' in response.text for response in responses) == 4
    with pg_app.app_context():
        assert len(get_db().execute(select(Card.id).where(Card.author_id == 1, Card.obra_id == 1)).fetchall()) == 1


def test_postgres_partial_index_allows_private_history_and_distinct_authors(pg_app):
    with pg_app.app_context():
        db = get_db()
        values = dict(titulo='História', capa='default-cover.svg', sobre='Experiência', nota=90, obra_id=1)
        with db:
            db.execute(insert(Card).values(**values, author_id=1))
        with pytest.raises(IntegrityError):
            with db:
                db.execute(insert(Card).values(**values, author_id=1))
        with db:
            db.execute(insert(Card).values(**values, author_id=1, archived=1))
            db.execute(insert(Card).values(**values, author_id=2))
        with pytest.raises(IntegrityError):
            with db:
                db.execute(update(Card).where(Card.author_id == 1, Card.archived == 1).values(archived=0))
        assert len(db.execute(select(Card.id).where(Card.obra_id == 1)).fetchall()) == 3
