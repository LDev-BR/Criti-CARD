from datetime import datetime, timezone

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from criticard import create_app
from criticard.config import ROOT
from criticard.db import get_db


def test_upgrade_preserves_unknown_dates_and_identifies_pioneers(tmp_path):
    path = tmp_path/'old.db'
    engine = create_engine('sqlite:///'+str(path))
    with engine.begin() as connection:
        config = Config()
        config.set_main_option('script_location', str(ROOT/'migrations'))
        config.attributes['connection'] = connection
        command.upgrade(config,'0011_unique_cards')
        for uid, date in [(42,'2020-01-02 00:00:00'),(43,None)]:
            connection.execute(text('INSERT INTO usuarios (id,username,nome,apelido,about,email,senha,admin,created_at) '
                'VALUES (:id,:name,:name,\'Leitor\',\'Bio\',:email,\'unchanged\',1,:date)'),
                dict(id=uid,name=f'OLD{uid}',email=f'{uid}@example.com',date=date))
        connection.execute(text("INSERT INTO cards(id,titulo,capa,sobre,nota,author_id) VALUES(7,'Old','same.png','Preserved',90,42)"))
    engine.dispose()
    config = dict(TESTING=True,SECRET_KEY='test',DATABASE=str(path),UPLOAD_FOLDER=str(tmp_path/'a'),CAPA_FOLDER=str(tmp_path/'c'))
    for _ in range(2):
        app = create_app(config)
        with app.app_context():
            db = get_db()
            profiles = db.execute('SELECT * FROM progression_profiles ORDER BY user_id').fetchall()
            assert len(profiles) == 2
            assert [p['is_pioneer'] for p in profiles] == [1,1]
            assert all(p['xp']==0 and p['history_imported_at'] is None for p in profiles)
            assert profiles[0]['membership_origin'] == 'signup'
            assert profiles[1]['membership_origin'] == 'rollout'
            assert db.execute('SELECT created_at FROM usuarios WHERE id=43').scalar() is None
            assert db.execute('SELECT senha FROM usuarios WHERE id=42').scalar() == 'unchanged'
            assert db.execute('SELECT sobre FROM cards WHERE id=7').scalar() == 'Preserved'
    with app.app_context():
        db = get_db()
        db.execute("INSERT INTO experience_events(user_id,event_key,kind,origin,delta,created_at,quota_day,rule_version) VALUES(42,'card:1','card_published','live',40,'2026-10-11','2026-10-11',1)")
        for table in ('achievement_grants','reward_grants'):
            db.execute(f"INSERT INTO {table}(user_id,slug,granted_at) VALUES(42,'pioneer','2026-10-11')")
        db.execute('DELETE FROM cards WHERE author_id=42')
        db.execute('DELETE FROM usuarios WHERE id=42')
        db.commit()
        for table in ('progression_profiles','experience_events','achievement_grants','reward_grants'):
            assert db.execute(f'SELECT COUNT(*) FROM {table} WHERE user_id=42').scalar() == 0
