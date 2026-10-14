"""Duplicate reviews become private history without rewriting any original data."""
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import insert

from criticard.config import ROOT
from criticard.db import get_db, upgrade_database
from criticard.social.models import CardLike, Comment


@pytest.mark.parametrize('policy,published,archived', [('latest',3,2), ('oldest',2,3)])
def test_upgrade_preserves_duplicates_and_their_relationships(app, policy, published, archived):
    engine = app.extensions['database_engine']
    config = Config()
    config.set_main_option('script_location', str(ROOT / 'migrations'))
    with engine.begin() as connection:
        config.attributes['connection'] = connection
        command.downgrade(config, '0010_catalog_admin')
    with app.app_context():
        db = get_db()
        with db:
            for identity, body in [(2, 'Primeira crítica'), (3, 'Segunda crítica')]:
                db.execute('INSERT INTO cards(id,author_id,obra_id,titulo,capa,sobre,nota) VALUES(?,1,1,?,?,?,90)',
                    (identity, 'Título histórico', 'shared.png', body))
            db.execute(insert(CardLike).values(user_id=2, card_id=2))
            db.execute(insert(Comment).values(author_id=2, card_id=2, body='Conversa preservada'))
        tables = {'cards': ('id','titulo','capa','sobre','nota','author_id','obra_id','created_at','updated_at','search_title'),
            'card_likes': ('id','user_id','card_id','created_at'),
            'comments': ('id','author_id','card_id','body','created_at','updated_at')}
        original = {table: db.execute('SELECT '+','.join(columns)+' FROM '+table+' ORDER BY id').fetchall()
            for table, columns in tables.items()}
        upgrade_database(keep_duplicate_review=policy)
        upgrade_database(keep_duplicate_review=policy)
        for table, columns in tables.items():
            assert db.execute('SELECT '+','.join(columns)+' FROM '+table+' ORDER BY id').fetchall() == original[table]
        assert db.execute('SELECT id FROM cards WHERE obra_id=1 AND archived=0').scalar() == published
        assert db.execute('SELECT id FROM cards WHERE archived=1').scalar() == archived
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []
        assert db.execute('SELECT version_num FROM alembic_version').scalar() == '0016_discovery_follows'


def test_invalid_migration_preference_is_rejected_before_changes(app):
    with pytest.raises(ValueError):
        upgrade_database(app, keep_duplicate_review='unknown')
