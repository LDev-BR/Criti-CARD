import sqlite3
import warnings

from criticard import create_app
from criticard.db import get_db


def test_legacy_database_is_upgraded_with_versions_and_preserved_data(tmp_path):
    path = tmp_path / 'legacy.db'
    with sqlite3.connect(path) as db:
        db.executescript('''
            CREATE TABLE usuarios(id INTEGER PRIMARY KEY,username TEXT UNIQUE NOT NULL,nome TEXT NOT NULL,
                apelido TEXT NOT NULL,imagem TEXT,about TEXT NOT NULL,email TEXT UNIQUE NOT NULL,senha TEXT NOT NULL,admin INTEGER DEFAULT 0);
            CREATE TABLE cards(id INTEGER PRIMARY KEY,titulo TEXT NOT NULL,capa TEXT NOT NULL,sobre TEXT NOT NULL,
                nota INTEGER NOT NULL,card_id INTEGER NOT NULL REFERENCES usuarios(id));
            INSERT INTO usuarios VALUES(42,'LEGACY','Legacy','Leitor','old.jpg','Bio','legacy@example.com','preserved-hash',0);
            INSERT INTO cards VALUES(7,'Berserk','preserved.png','Review',80,42);
        ''')
    config = {'TESTING':True,'SECRET_KEY':'test','DATABASE':str(path),
              'UPLOAD_FOLDER':str(tmp_path/'avatars'),'CAPA_FOLDER':str(tmp_path/'covers')}
    for _ in range(2):
        app = create_app(config)
        with app.app_context():
            db = get_db()
            assert db.execute('SELECT version_num FROM alembic_version').fetchall()
            card = db.execute('SELECT * FROM cards WHERE id=7').fetchone()
            assert card['author_id'] == 42 and card['capa'] == 'preserved.png'
            assert card['obra_id'] is not None and card['created_at'] is None
            assert db.execute('SELECT senha FROM usuarios WHERE id=42').scalar() == 'preserved-hash'
            assert db.execute('SELECT COUNT(*) FROM obras').scalar() == 30


def test_normal_startup_does_not_modify_database(tmp_path):
    config = {'TESTING':True,'SECRET_KEY':'test','DATABASE':str(tmp_path/'fresh.db'),
              'UPLOAD_FOLDER':str(tmp_path/'avatars'),'CAPA_FOLDER':str(tmp_path/'covers')}
    create_app(config)
    before = (tmp_path/'fresh.db').read_bytes()
    create_app(dict(config, TESTING=False))
    assert (tmp_path/'fresh.db').read_bytes() == before


def test_migration_timestamps_use_explicit_sqlite_types(tmp_path):
    from sqlalchemy import select
    from criticard.communities.models import Community
    from criticard.models import utcnow
    from criticard.progression.policy import as_utc

    before = utcnow()
    with warnings.catch_warnings():
        warnings.filterwarnings('error', message='The default datetime adapter is deprecated.*',
                                category=DeprecationWarning)
        app = create_app({'TESTING': True, 'SECRET_KEY': 'migration-timestamp-test',
                          'DATABASE': str(tmp_path / 'timestamps.db'),
                          'UPLOAD_FOLDER': str(tmp_path / 'avatars'),
                          'CAPA_FOLDER': str(tmp_path / 'covers')})
    after = utcnow()
    with app.app_context():
        communities = get_db().execute(select(Community.created_at, Community.updated_at)).fetchall()
        assert len(communities) == 6
        assert all(before <= as_utc(row['created_at']) <= after for row in communities)
        assert all(row['created_at'] == row['updated_at'] for row in communities)
