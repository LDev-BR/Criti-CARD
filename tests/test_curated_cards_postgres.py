"""Publication must observe administrator changes that precede its work lock."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from time import monotonic, sleep

import pytest
from sqlalchemy import select, text, update

from criticard.db import get_db
from criticard.models import Card, User, Work
from criticard.security import session_identity
from conftest import post
from test_postgres import pg_app, pg_database_url  # noqa: F401


@pytest.mark.parametrize('change', ['retirement', 'cover'])
def test_publication_waits_for_catalog_change_and_uses_committed_values(pg_app, change):
    locked, release = Event(), Event()
    def administrator_change():
        with pg_app.app_context():
            with get_db() as db:
                values = {'active': 0} if change == 'retirement' else {'capa': 'catalog:jogos:1'}
                db.execute(update(Work).where(Work.id == 1).values(**values))
                locked.set()
                assert release.wait(timeout=10)

    def publish():
        client = pg_app.test_client()
        with pg_app.app_context():
            user = get_db().execute(select(User).where(User.id == 1)).fetchone()
            stamp = session_identity(user)
        with client.session_transaction() as session:
            session.update(usuario_id=1, session_version=user['session_version'], auth_stamp=stamp)
        return post(client, '/cadastro_cards', {'obra_id': '1', 'sobre': 'Publicação concorrente', 'nota': '90'})

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            administrator = pool.submit(administrator_change)
            assert locked.wait(timeout=10)
            author = pool.submit(publish)
            waiting = False
            deadline = monotonic() + 5
            while monotonic() < deadline and not waiting:
                if author.done():
                    author.result()
                with pg_app.extensions['database_engine'].connect() as observer:
                    waiting = observer.execute(text("SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND wait_event_type='Lock'")).scalar() > 0
                if not waiting:
                    sleep(.02)
            assert waiting, 'Publication must wait for the catalog work lock'
            release.set()
            administrator.result(timeout=10)
            response = author.result(timeout=10)
    finally:
        release.set()
    with pg_app.app_context():
        card = get_db().execute(select(Card).where(Card.id == 2)).fetchone()
        if change == 'retirement':
            assert response.status_code == 200 and 'obra_id-error' in response.text
            assert card is None
        else:
            assert response.status_code == 302 and card['capa'] == 'catalog:jogos:1'
