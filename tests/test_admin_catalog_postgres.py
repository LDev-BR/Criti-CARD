"""Real PostgreSQL catalog concurrency, session revocation and preservation."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from time import monotonic, sleep

import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError

from criticard.db import get_db
from criticard.models import Card, User, Work
from criticard.security import session_identity
from criticard.validation import FormValidationError
from test_postgres import in_app, pg_app, pg_database_url  # noqa: F401


def credentials(app, user_id=3):
    with app.app_context():
        user = get_db().execute(select(User).where(User.id == user_id)).fetchone()
        return {'usuario_id': user_id, 'session_version': user['session_version'],
                'auth_stamp': session_identity(user)}


def test_postgres_admins_cannot_concurrently_create_casefold_duplicate(pg_app):
    from criticard.admin_catalog.service import create_work
    with pg_app.app_context():
        db = get_db()
        with db:
            db.execute(update(User).where(User.id == 2).values(admin=1))
    identities = {user_id: credentials(pg_app, user_id) for user_id in (2, 3)}
    def create(index):
        user_id = 2 + index % 2
        title = 'Straße' if index % 2 else 'STRASSE'
        try:
            return in_app(pg_app, lambda: create_work(user_id, identities[user_id],
                {'titulo': title, 'categoria_id': '1'}, 'new.png'))['id']
        except FormValidationError:
            return None
    with ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(create, range(5)))
    assert sum(value is not None for value in results) == 1
    with pg_app.app_context():
        assert get_db().execute(select(func.count()).select_from(Work).where(Work.search_title == 'strasse')).scalar() == 1


def test_postgres_catalog_active_constraint_rejects_invalid_value(pg_app):
    with pg_app.app_context():
        db = get_db()
        with pytest.raises(IntegrityError):
            with db:
                db.execute(update(Work).where(Work.id == 1).values(active=2))
        assert db.execute(select(Work.active).where(Work.id == 1)).scalar() == 1


def test_postgres_retirement_keeps_existing_backlog_and_cards(pg_app):
    from criticard.admin_catalog.service import edit_work, retire_work, restore_work
    from criticard.backlog.service import add_item, collection_items
    from criticard.catalog import selected_work
    identity = credentials(pg_app)
    with pg_app.app_context():
        db = get_db()
        with db:
            db.execute(update(Card).where(Card.id == 1).values(obra_id=1))
        add_item(1, {'obra_id': '1'})
        edit_work(3, identity, 1, {'titulo': 'Nova identidade', 'categoria_id': '2'})
        retire_work(3, identity, 1)
        card = db.execute(select(Card).where(Card.id == 1)).fetchone()
        assert card['titulo'] == 'Card da Alice' and card['capa'] == 'isolated.png'
        assert selected_work({'obra_id': '1'}, card)['capa'] == 'catalog:jogos:0'
        with pytest.raises(FormValidationError):
            selected_work({'obra_id': '1'})
        assert collection_items(1, {'categoria': '', 'q': '', 'status': ''})[0]['work_id'] == 1
        restore_work(3, identity, 1)
        assert db.execute(select(Work.active).where(Work.id == 1)).scalar() == 1


def test_postgres_role_revocation_waits_for_authorized_catalog_transaction(pg_app, monkeypatch):
    from criticard.admin_catalog import service
    identity = credentials(pg_app)
    locked, release = Event(), Event()
    original_validate = service._validated_values
    def hold_after_locks(data, **kwargs):
        locked.set()
        assert release.wait(timeout=10)
        return original_validate(data, **kwargs)
    monkeypatch.setattr(service, '_validated_values', hold_after_locks)
    def create():
        return in_app(pg_app, lambda: service.create_work(3, identity,
            {'titulo': 'Criada antes da revogação', 'categoria_id': '1'}, 'new.png'))
    def revoke():
        def transaction():
            db = get_db()
            with db:
                db.execute(update(User).where(User.id == 3).values(admin=0))
        return in_app(pg_app, transaction)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            writer = pool.submit(create)
            assert locked.wait(timeout=10)
            revoker = pool.submit(revoke)
            deadline = monotonic() + 5
            waiting = False
            while monotonic() < deadline and not waiting:
                with pg_app.extensions['database_engine'].connect() as observer:
                    waiting = observer.execute(text("SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND wait_event_type='Lock'")).scalar() > 0
                if not waiting:
                    sleep(.02)
            assert waiting, 'Role revocation must wait for the administrator row lock'
            release.set()
            assert writer.result(timeout=10)['titulo'] == 'Criada antes da revogação'
            revoker.result(timeout=10)
    finally:
        release.set()
    monkeypatch.setattr(service, '_validated_values', original_validate)
    from werkzeug.exceptions import Forbidden
    with pg_app.app_context():
        with pytest.raises(Forbidden):
            service.create_work(3, identity, {'titulo': 'Proibida', 'categoria_id': '1'}, 'new2.png')


def test_postgres_adding_backlog_waits_for_retirement_and_then_rejects(pg_app):
    from criticard.backlog.service import add_item
    from werkzeug.exceptions import NotFound
    locked, release = Event(), Event()
    def retire_with_lock():
        def transaction():
            db = get_db()
            with db:
                db.execute(select(Work.id).where(Work.id == 1).with_for_update()).fetchone()
                locked.set()
                assert release.wait(timeout=10)
                db.execute(update(Work).where(Work.id == 1).values(active=0))
        return in_app(pg_app, transaction)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            retirement = pool.submit(retire_with_lock)
            assert locked.wait(timeout=10)
            addition = pool.submit(lambda: in_app(pg_app, lambda: add_item(1, {'obra_id': '1'})))
            deadline = monotonic() + 5
            waiting = False
            while monotonic() < deadline and not waiting:
                with pg_app.extensions['database_engine'].connect() as observer:
                    waiting = observer.execute(text("SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND wait_event_type='Lock'")).scalar() > 0
                if not waiting:
                    sleep(.02)
            assert waiting, 'Collection insertion must wait for the current work row'
            release.set()
            retirement.result(timeout=10)
            with pytest.raises(NotFound):
                addition.result(timeout=10)
    finally:
        release.set()
