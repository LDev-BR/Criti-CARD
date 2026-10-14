"""Only untouched migration seeds may be replaced during database transfer."""
from datetime import datetime, timezone

import pytest
from sqlalchemy import delete, func, insert, select, update

from criticard import create_app
from criticard.communities.models import (
    Community, CommunityComment, CommunityInvite, CommunityJoinRequest,
    CommunityMembership, CommunityPost, CommunityReaction,
)
from criticard.db import get_db
from criticard.models import Category, User, Work
from criticard.transfer import TransferError, _assert_empty_target, _metadata, import_sqlite
from test_postgres import pg_database_url
from test_transfer import configuration, digest


@pytest.fixture
def seed_app(tmp_path):
    app = create_app(configuration(tmp_path))
    yield app
    app.extensions['database_engine'].dispose()


@pytest.fixture
def pg_seed_app(pg_database_url, tmp_path):
    app = create_app(configuration(tmp_path, DATABASE_URL=pg_database_url))
    yield app
    app.extensions['database_engine'].dispose()


def test_fresh_migration_community_seed_is_an_empty_transfer_target(seed_app):
    with seed_app.extensions['database_engine'].connect() as connection:
        assert connection.execute(select(func.count()).select_from(Community)).scalar() == 6
        _assert_empty_target(connection, _metadata(connection))


def test_completely_empty_tables_remain_an_empty_transfer_target(seed_app):
    with seed_app.extensions['database_engine'].begin() as connection:
        for model in (Community, Work, Category):
            connection.execute(delete(model))
        _assert_empty_target(connection, _metadata(connection))


def test_custom_community_with_a_seeded_flag_is_not_an_empty_target(seed_app):
    with seed_app.extensions['database_engine'].begin() as connection:
        connection.execute(delete(Community).where(Community.slug == 'tema-jogos'))
        connection.execute(insert(Community).values(
            slug='custom-seeded', name='Comunidade personalizada', seeded=1))
        with pytest.raises(TransferError):
            _assert_empty_target(connection, _metadata(connection))
        assert connection.execute(select(Community.name).where(
            Community.slug == 'custom-seeded')).scalar() == 'Comunidade personalizada'


@pytest.mark.parametrize('changes', [
    {'slug': 'tema-jogos-editado'},
    {'name': 'Jogos personalizados'},
    {'description': 'Descrição escrita por uma pessoa.'},
    {'theme': 'gold'},
    {'icon': 'book'},
    {'cover': 'custom-cover.png'},
    {'mode': 'closed'},
    {'minimum_level': 2},
    {'seeded': 0},
    {'archived': 1},
    {'category_id': None},
    {'updated_at': datetime(2000, 1, 1, tzinfo=timezone.utc)},
    {'created_at': datetime(2000, 1, 1, tzinfo=timezone.utc),
     'updated_at': datetime(2000, 1, 1, tzinfo=timezone.utc)},
], ids=['slug', 'name', 'description', 'theme', 'icon', 'cover', 'mode',
        'level', 'seeded', 'archived', 'category', 'updated', 'both-dates'])
def test_modified_initial_community_seed_is_not_an_empty_target(seed_app, changes):
    with seed_app.extensions['database_engine'].begin() as connection:
        connection.execute(update(Community).where(Community.slug == 'tema-jogos').values(**changes))
        with pytest.raises(TransferError):
            _assert_empty_target(connection, _metadata(connection))


def test_partial_initial_community_seed_is_not_an_empty_target(seed_app):
    with seed_app.extensions['database_engine'].begin() as connection:
        connection.execute(delete(Community).where(Community.slug == 'tema-jogos'))
        with pytest.raises(TransferError):
            _assert_empty_target(connection, _metadata(connection))
        assert connection.execute(select(func.count()).select_from(Community)).scalar() == 5


@pytest.mark.parametrize('changes', [
    {'capa': 'custom-cover.png'},
    {'active': 0},
    {'created_at': datetime(2000, 1, 1, tzinfo=timezone.utc)},
], ids=['cover', 'archived', 'created'])
def test_modified_initial_catalog_is_not_an_empty_target(seed_app, changes):
    with seed_app.extensions['database_engine'].begin() as connection:
        # An empty community table keeps this test focused on catalog validation.
        connection.execute(delete(Community))
        connection.execute(update(Work).where(Work.id == 1).values(**changes))
        with pytest.raises(TransferError):
            _assert_empty_target(connection, _metadata(connection))


def test_initial_communities_detached_from_catalog_are_not_an_empty_target(seed_app):
    with seed_app.extensions['database_engine'].begin() as connection:
        connection.execute(delete(Work))
        connection.execute(delete(Category))
        with pytest.raises(TransferError):
            _assert_empty_target(connection, _metadata(connection))


@pytest.fixture
def community_source(tmp_path):
    source = tmp_path / 'community-source.db'
    app = create_app(configuration(tmp_path, DATABASE=str(source)))
    with app.app_context():
        db = get_db()
        with db:
            for user_id in (42, 77):
                db.execute(insert(User).values(
                    id=user_id, username=f'PERSON{user_id}', nome='Pessoa', apelido='Leitor',
                    about='Bio', email=f'person{user_id}@example.com', senha='preserved-hash'))
            db.execute(update(Community).where(Community.slug == 'tema-jogos').values(
                name='Jogos da origem', description='Comunidade inicial personalizada na origem.'))
            seeded_id = db.execute(select(Community.id).where(Community.slug == 'tema-jogos')).scalar()
            db.execute(insert(Community).values(id=20, slug='clube-da-origem',
                name='Clube da origem', description='Discussões privadas', mode='closed',
                minimum_level=2, created_by=42, cover='source-cover.png'))
            db.execute(insert(CommunityMembership), [
                {'community_id': 20, 'user_id': 42, 'role': 'owner'},
                {'community_id': seeded_id, 'user_id': 77, 'role': 'member'},
            ])
            db.execute(insert(CommunityJoinRequest).values(id=31, community_id=20, user_id=77))
            db.execute(insert(CommunityInvite).values(id=33, community_id=20, inviter_id=42, invitee_id=77))
            db.execute(insert(CommunityPost).values(id=70, community_id=20, author_id=42,
                work_id=1, title='Conversa da origem', body='Publicação preservada.'))
            db.execute(insert(CommunityComment).values(id=71, post_id=70, author_id=77,
                body='Comentário preservado.'))
            db.execute(insert(CommunityReaction).values(id=72, post_id=70, user_id=77, kind='insightful'))
    app.extensions['database_engine'].dispose()
    return source


def test_postgres_import_preserves_source_communities_and_membership_links(pg_seed_app, community_source):
    before = digest(community_source)
    with pg_seed_app.app_context():
        report = import_sqlite(community_source, confirm_empty_target=True)
        db = get_db()
        assert report['counts']['communities'] == 7
        assert report['counts']['community_memberships'] == 2
        assert db.execute(select(Community.name).where(Community.slug == 'tema-jogos')).scalar() == 'Jogos da origem'
        community = db.execute(select(Community).where(Community.id == 20)).fetchone()
        assert (community['mode'], community['cover'], community['created_by']) == ('closed', 'source-cover.png', 42)
        assert db.execute(select(CommunityMembership.role).where(
            CommunityMembership.community_id == 20, CommunityMembership.user_id == 42)).scalar() == 'owner'
        assert db.execute(select(CommunityPost.work_id).where(CommunityPost.id == 70)).scalar() == 1
        assert db.execute(select(CommunityComment.body).where(CommunityComment.id == 71)).scalar() == 'Comentário preservado.'
        assert db.execute(select(CommunityReaction.kind).where(CommunityReaction.id == 72)).scalar() == 'insightful'
        assert db.execute(select(CommunityInvite.invitee_id).where(CommunityInvite.id == 33)).scalar() == 77
        assert db.execute(select(CommunityJoinRequest.user_id).where(CommunityJoinRequest.id == 31)).scalar() == 77
        with db:
            next_id = db.execute(insert(Community).values(slug='next-community', name='Próxima').returning(Community.id)).scalar()
        assert next_id > 20
    assert digest(community_source) == before


def test_postgres_community_import_dry_run_preserves_seed_rows_and_sequences(pg_seed_app, community_source):
    before = digest(community_source)
    with pg_seed_app.app_context():
        db = get_db()
        original_seed = db.execute(select(Community).order_by(Community.id)).fetchall()
        db.rollback()
        report = import_sqlite(community_source, confirm_empty_target=True, dry_run=True)
        assert report['counts']['communities'] == 7
        assert db.execute(select(Community).order_by(Community.id)).fetchall() == original_seed
        assert db.execute(select(func.count()).select_from(CommunityMembership)).scalar() == 0
        with db:
            next_id = db.execute(insert(Community).values(slug='after-dry-run', name='Após ensaio').returning(Community.id)).scalar()
        assert next_id == 7
    assert digest(community_source) == before


def test_postgres_import_refuses_custom_target_community(pg_seed_app, community_source):
    before = digest(community_source)
    with pg_seed_app.app_context():
        db = get_db()
        with db:
            db.execute(update(Community).where(Community.slug == 'tema-jogos').values(name='Personalizada no destino'))
        with pytest.raises(TransferError):
            import_sqlite(community_source, confirm_empty_target=True)
        assert db.execute(select(Community.name).where(Community.slug == 'tema-jogos')).scalar() == 'Personalizada no destino'
        assert db.execute(select(func.count()).select_from(User)).scalar() == 0
    assert digest(community_source) == before
