"""Import preparation never changes source data or nonempty destinations."""
import hashlib
import os
import sqlite3
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import func, insert, select, text, update

from criticard import create_app
from criticard.db import get_db
from criticard.models import Card, User, Work


def configuration(tmp_path, **overrides):
    return {'TESTING': True, 'SECRET_KEY': 'transfer-isolated-test-key',
        'DATABASE': str(tmp_path / 'target.db'), 'DATABASE_URL': None,
        'UPLOAD_FOLDER': str(tmp_path / 'avatars'), 'CAPA_FOLDER': str(tmp_path / 'covers'),
        'ADM_USERNAME': '', 'ADM_SENHA': '', **overrides}


@pytest.fixture
def target_app(tmp_path):
    app = create_app(configuration(tmp_path))
    yield app
    app.extensions['database_engine'].dispose()


@pytest.fixture
def legacy_source(tmp_path):
    source = tmp_path / 'legacy-source.db'
    with sqlite3.connect(source) as db:
        db.executescript('''
            CREATE TABLE usuarios(id INTEGER PRIMARY KEY,username TEXT UNIQUE NOT NULL,nome TEXT NOT NULL,
                apelido TEXT NOT NULL,imagem TEXT,about TEXT NOT NULL,email TEXT UNIQUE NOT NULL,senha TEXT NOT NULL,admin INTEGER DEFAULT 0);
            CREATE TABLE cards(id INTEGER PRIMARY KEY,titulo TEXT NOT NULL,capa TEXT NOT NULL,sobre TEXT NOT NULL,
                nota INTEGER NOT NULL,card_id INTEGER NOT NULL REFERENCES usuarios(id));
            INSERT INTO usuarios VALUES(42,'LEGACY','Pessoa original','Leitor','old-avatar.jpg','Bio','legacy@example.com','preserved-hash',0);
            INSERT INTO cards VALUES(7,'Berserk','old-cover.png','Crítica preservada',80,42);
        ''')
    return source


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_sqlite_backup_migrates_only_an_isolated_copy(legacy_source):
    from criticard.transfer import prepared_sqlite_source
    before = digest(legacy_source)
    with prepared_sqlite_source(legacy_source) as engine:
        assert str(engine.url.database) != str(legacy_source)
        with engine.connect() as db:
            assert db.execute(text('SELECT author_id FROM cards WHERE id=7')).scalar() == 42
            assert db.execute(text('SELECT senha FROM usuarios WHERE id=42')).scalar() == 'preserved-hash'
            assert db.execute(text('SELECT created_at FROM cards WHERE id=7')).scalar() is None
            assert db.execute(text('SELECT COUNT(*) FROM obras')).scalar() == 30
            assert db.execute(text('SELECT COUNT(*) FROM alembic_version')).scalar() >= 1
        copy_path = engine.url.database
    assert not os.path.exists(copy_path)
    assert digest(legacy_source) == before
    with sqlite3.connect(legacy_source) as db:
        assert 'card_id' in {row[1] for row in db.execute('PRAGMA table_info(cards)')}


def test_import_requires_postgres_and_confirmation(target_app, legacy_source):
    from criticard.transfer import TransferError, import_sqlite
    with target_app.app_context():
        with pytest.raises(TransferError):
            import_sqlite(legacy_source, confirm_empty_target=True)
        with pytest.raises(TransferError):
            import_sqlite(legacy_source)
        assert get_db().execute(select(func.count()).select_from(User)).scalar() == 0


def test_cli_confirmation_gate_has_no_source_side_effect(target_app, legacy_source):
    before = digest(legacy_source)
    result = target_app.test_cli_runner().invoke(args=['db-import-sqlite', str(legacy_source)])
    assert result.exit_code != 0
    assert 'confirm-empty-target' in result.output
    assert digest(legacy_source) == before


def modern_source(legacy_source, tmp_path):
    from criticard.backlog.models import BacklogItem
    from criticard.chat import service as chat
    from criticard.chat.models import Message
    from criticard.accounts.models import AccountToken
    from criticard.social.models import CardLike, Comment
    app = create_app(configuration(tmp_path, DATABASE=str(legacy_source)))
    with app.app_context():
        db = get_db()
        with db:
            db.execute(insert(User).values(id=77, username='BOB', nome='Bob', apelido='Leitor',
                about='Bio', email='bob@example.com', senha='second-preserved-hash'))
            db.execute(insert(BacklogItem).values(id=12, user_id=42, work_id=30,
                status='planned', visibility='private', progress=None, progress_unit=None))
            db.execute(insert(CardLike).values(id=19, user_id=77, card_id=7))
            db.execute(insert(Comment).values(id=22, author_id=77, card_id=7, body='Comentário importado'))
        conversation, _ = chat.start_conversation(42, 77)
        message, _ = chat.send_message(42, conversation['id'], 'Mensagem importada', str(uuid4()))
        chat.mark_read(77, conversation['id'], message['id'])
        with db:
            db.execute(update(Message).where(Message.id == message['id']).values(
                created_at=datetime(2020, 2, 3, 4, 5, 6, tzinfo=timezone.utc)))
            db.execute(insert(AccountToken).values(id=9, user_id=42, token_hash='a' * 64,
                purpose='verify', email_snapshot='legacy@example.com', session_version=0,
                expires_at=datetime(2030, 1, 1, tzinfo=timezone.utc), used_at=None))
    app.extensions['database_engine'].dispose()
    return legacy_source


def test_postgres_import_preserves_ids_hashes_links_nulls_and_sequences(pg_empty_app, legacy_source, tmp_path):
    from criticard.transfer import import_sqlite
    from criticard.backlog.models import BacklogItem
    from criticard.chat.models import ConversationMember, Message
    from criticard.social.models import CardLike, Comment
    from criticard.accounts.models import AccountToken
    source = modern_source(legacy_source, tmp_path)
    before = digest(source)
    with pg_empty_app.app_context():
        report = import_sqlite(source, confirm_empty_target=True)
        db = get_db()
        assert report['counts']['usuarios'] == 2 and report['counts']['cards'] == 1
        assert db.execute(select(User.senha).where(User.id == 42)).scalar() == 'preserved-hash'
        card = db.execute(select(Card).where(Card.id == 7)).fetchone()
        assert card['author_id'] == 42 and card['capa'] == 'old-cover.png'
        assert card['created_at'] is None and card['updated_at'] is None and card['obra_id'] is not None
        assert db.execute(select(BacklogItem.progress).where(BacklogItem.id == 12)).scalar() is None
        assert db.execute(select(CardLike.user_id).where(CardLike.id == 19)).scalar() == 77
        assert db.execute(select(Comment.body).where(Comment.id == 22)).scalar() == 'Comentário importado'
        message = db.execute(select(Message)).fetchone()
        assert message['body'] == 'Mensagem importada'
        assert message['created_at'] == datetime(2020, 2, 3, 4, 5, 6, tzinfo=timezone.utc)
        token = db.execute(select(AccountToken).where(AccountToken.id == 9)).fetchone()
        assert token['token_hash'] == 'a' * 64 and token['used_at'] is None
        assert token['expires_at'] == datetime(2030, 1, 1, tzinfo=timezone.utc)
        assert db.execute(select(ConversationMember.last_read_id).where(ConversationMember.user_id == 77)).scalar() == message['id']
        with db:
            new_user = db.execute(insert(User).values(username='NEW', nome='New', apelido='Leitor', about='Bio',
                email='new@example.com', senha='hash').returning(User.id)).scalar()
            new_work = db.execute(insert(Work).values(categoria_id=1, titulo='Obra nova').returning(Work.id)).scalar()
        assert new_user > 77 and new_work > 30
    assert digest(source) == before


def test_postgres_dry_run_leaves_empty_target_unchanged(pg_empty_app, legacy_source):
    from criticard.transfer import import_sqlite
    with pg_empty_app.app_context():
        report = import_sqlite(legacy_source, confirm_empty_target=True, dry_run=True)
        db = get_db()
        assert report['dry_run'] is True and report['counts']['usuarios'] == 1
        assert db.execute(select(func.count()).select_from(User)).scalar() == 0
        assert db.execute(select(func.count()).select_from(Work)).scalar() == 30
        with db:
            user_id = db.execute(insert(User).values(username='AFTER_DRY_RUN', nome='Test',
                apelido='Leitor', about='Bio', email='after@example.com', senha='hash').returning(User.id)).scalar()
        assert user_id == 1


def test_postgres_import_refuses_existing_user_data(pg_empty_app, legacy_source):
    from criticard.transfer import TransferError, import_sqlite
    with pg_empty_app.app_context():
        db = get_db()
        with db:
            db.execute(insert(User).values(username='EXISTING', nome='Existente', apelido='Leitor', about='Bio',
                email='existing@example.com', senha='existing-hash'))
        with pytest.raises(TransferError):
            import_sqlite(legacy_source, confirm_empty_target=True)
        assert db.execute(select(User.username)).scalar() == 'EXISTING'
        assert db.execute(select(func.count()).select_from(Work)).scalar() == 30


def test_postgres_import_refuses_modified_catalog_seed(pg_empty_app, legacy_source):
    from criticard.transfer import TransferError, import_sqlite
    with pg_empty_app.app_context():
        db = get_db()
        with db:
            db.execute(update(Work).where(Work.id == 1).values(capa='custom-cover.png'))
        with pytest.raises(TransferError):
            import_sqlite(legacy_source, confirm_empty_target=True)
        assert db.execute(select(Work.capa).where(Work.id == 1)).scalar() == 'custom-cover.png'


def test_postgres_import_rolls_back_on_orphaned_source_links(pg_empty_app, legacy_source):
    from criticard.transfer import TransferError, import_sqlite
    with sqlite3.connect(legacy_source) as db:
        db.execute('UPDATE cards SET card_id=999 WHERE id=7')
    before = digest(legacy_source)
    with pg_empty_app.app_context():
        with pytest.raises(TransferError):
            import_sqlite(legacy_source, confirm_empty_target=True)
        db = get_db()
        assert db.execute(select(func.count()).select_from(User)).scalar() == 0
        assert db.execute(select(func.count()).select_from(Work)).scalar() == 30
    assert digest(legacy_source) == before


def test_postgres_import_rolls_back_when_destination_check_fails_after_copy_starts(pg_empty_app, legacy_source):
    from criticard.transfer import TransferError, import_sqlite
    # The original SQLite schema has no note-range constraint. PostgreSQL does.
    with sqlite3.connect(legacy_source) as db:
        db.execute('UPDATE cards SET nota=1000 WHERE id=7')
    before = digest(legacy_source)
    with pg_empty_app.app_context():
        with pytest.raises(TransferError):
            import_sqlite(legacy_source, confirm_empty_target=True)
        db = get_db()
        assert db.execute(select(func.count()).select_from(User)).scalar() == 0
        assert db.execute(select(func.count()).select_from(Card)).scalar() == 0
        assert db.execute(select(func.count()).select_from(Work)).scalar() == 30
        assert db.execute(select(Work.titulo).where(Work.id == 1)).scalar() == 'Elden Ring'
    assert digest(legacy_source) == before


def test_postgres_cli_import_verifies_counts_without_exposing_records(pg_empty_app, legacy_source):
    result = pg_empty_app.test_cli_runner().invoke(args=['db-import-sqlite', str(legacy_source), '--confirm-empty-target'])
    assert result.exit_code == 0, result.output
    assert 'usuarios: 1' in result.output and 'cards: 1' in result.output
    assert 'preserved-hash' not in result.output and 'legacy@example.com' not in result.output
    with pg_empty_app.app_context():
        assert get_db().execute(select(User.username).where(User.id == 42)).scalar() == 'LEGACY'


@pytest.fixture
def pg_empty_app(pg_database_url, tmp_path):
    app = create_app(configuration(tmp_path, DATABASE_URL=pg_database_url))
    yield app
    app.extensions['database_engine'].dispose()


from test_postgres import pg_database_url


def test_progression_transfer_preserves_corrections_legacy_dates_and_history_marker(pg_empty_app,legacy_source,tmp_path):
    from criticard.models import utcnow
    from criticard.progression.history import import_user_history
    from criticard.progression.models import ProgressionProfile, ExperienceEvent, RewardGrant
    from criticard.progression.service import record_action, record_event, revoke_event
    from criticard.progression.policy import as_utc
    from criticard.settings.service import save_preferences, get_preferences
    from criticard.transfer import import_sqlite
    source = modern_source(legacy_source,tmp_path)
    application = create_app(configuration(tmp_path,DATABASE=str(source)))
    with application.app_context():
        db = get_db()
        with db:
            db.execute(update(User).where(User.id==77).values(admin=1))
            import_user_history(db,42,utcnow())
            # The imported legacy review contributes 40 XP. Add 970 historical
            # XP so two live reviews cross the current 1,100 XP slate tier;
            # reversing the first review must then revoke the equipped frame.
            now = utcnow()
            for work_id in range(4, 23):
                record_event(db,42,'card_published',f'card:{work_id}',now,
                    work_id=work_id,category_id=1,origin='history')
            for work_id in range(1, 15):
                record_event(db,42,'work_completed',f'completed:{work_id}',now,
                    work_id=work_id,category_id=1,origin='history')
            first = record_action(db,42,'card_published',utcnow(),work_id=1,category_id=1)
            record_action(db,42,'card_published',utcnow(),work_id=2,category_id=1)
        save_preferences(42,'chat',{'chat_enter_send':False})
        save_preferences(42,'jornada',{'progression_frame':'frame_slate'})
        with db:
            revoke_event(db,77,first.event_id,'Abuso confirmado antes da transferência.',utcnow())
        original_profile = db.execute(select(ProgressionProfile).where(ProgressionProfile.user_id==42)).fetchone()
        original_events = db.execute(select(ExperienceEvent).where(ExperienceEvent.user_id==42).order_by(ExperienceEvent.id)).fetchall()
        original_preferences = get_preferences(42)
    application.extensions['database_engine'].dispose()
    before = digest(source)
    with pg_empty_app.app_context():
        report = import_sqlite(source,confirm_empty_target=True,dry_run=True)
        assert report['counts']['experience_events']>=4
        assert get_db().execute(select(ProgressionProfile)).fetchone() is None
        # Close this observation before the importer acquires ACCESS EXCLUSIVE
        # on its own connection; otherwise the test blocks its own import.
        get_db().rollback()
        import_sqlite(source,confirm_empty_target=True)
        db = get_db()
        profile = db.execute(select(ProgressionProfile).where(ProgressionProfile.user_id==42)).fetchone()
        assert profile['xp']==original_profile['xp']==1060
        assert profile['is_pioneer']==1 and profile['membership_origin']=='rollout'
        assert db.execute(select(User.created_at).where(User.id==42)).scalar() is None
        assert profile['membership_since']==as_utc(original_profile['membership_since'])
        assert profile['history_imported_at']==as_utc(original_profile['history_imported_at'])
        events = db.execute(select(ExperienceEvent).where(ExperienceEvent.user_id==42).order_by(ExperienceEvent.id)).fetchall()
        assert [(e['event_key'],e['delta'],e['reverses_event_id']) for e in events]==[
            (e['event_key'],e['delta'],e['reverses_event_id']) for e in original_events]
        assert get_preferences(42)==original_preferences
        grant = db.execute(select(RewardGrant).where(RewardGrant.user_id==42,RewardGrant.slug=='frame_slate')).fetchone()
        assert grant['revoked_at'] is not None
        with db:
            assert import_user_history(db,42,utcnow())['xp']==0
    assert digest(source)==before
