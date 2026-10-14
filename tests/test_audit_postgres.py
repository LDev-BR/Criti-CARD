"""Audit regressions against the opt-in, disposable PostgreSQL fixture."""
from sqlalchemy import insert, select

from criticard.chat.service import conversations
from criticard.communities.models import Community
from criticard.db import get_db
from criticard.models import User
from criticard.security import session_identity
from criticard.social.models import Block, Comment
from test_chat_query_efficiency import (
    add_direct, add_group, add_message, add_user, counted_statements,
)
from test_postgres import pg_app, pg_database_url  # noqa: F401


def test_postgres_audit_chat_lists_batch_direct_and_group_summaries(pg_app):
    with pg_app.app_context():
        db = get_db()
        with db:
            for conversation_id in range(1, 12):
                peer_id = conversation_id + 1
                if peer_id > 3:
                    add_user(db, peer_id)
                add_direct(db, conversation_id, peer_id)
                add_message(db, conversation_id, conversation_id, peer_id, 'Conversa direta')
            add_group(db, 20, 1, [(1, 'owner'), (2, 'member')])
            add_group(db, 21, 1, [(1, 'owner')], archived=True)
            add_message(db, 20, 20, 2, 'Conversa em grupo')

        with counted_statements(pg_app.extensions['database_engine']) as statements:
            result = conversations(1)

        assert len(statements) <= 6
        assert len(result['conversations']) == 12
        assert result['unread_count'] == 12
        assert result['conversations'][0]['id'] == 20
        assert result['conversations'][0]['group']['member_count'] == 2
        assert result['conversations'][0]['group']['role'] == 'owner'
        assert result['conversations'][0]['group']['members'] == []


def test_postgres_audit_blocked_comments_are_absent_from_json(pg_app):
    with pg_app.app_context():
        db = get_db()
        with db:
            db.execute(insert(Comment), [
                {'card_id': 1, 'author_id': 2, 'body': 'Comentario bloqueado'},
                {'card_id': 1, 'author_id': 1, 'body': 'Comentario visivel'},
            ])
            db.execute(insert(Block).values(user_id=2, target_id=1))
        user = db.execute(select(User).where(User.id == 1)).fetchone()
        stamp = session_identity(user)
    client = pg_app.test_client()
    with client.session_transaction() as session:
        session.update(usuario_id=1, session_version=user['session_version'], auth_stamp=stamp)
    response = client.get('/social/cards/1/comments', headers={'Accept': 'application/json'})
    assert response.status_code == 200
    assert response.json['total'] == 1
    assert [comment['body'] for comment in response.json['comments']] == ['Comentario visivel']


def test_postgres_audit_oversized_community_post_id_returns_client_error(pg_app):
    with pg_app.app_context():
        slug = get_db().execute(select(Community.slug).limit(1)).scalar()
    assert pg_app.test_client().get(f'/comunidades/{slug}/publicacoes/{2 ** 63}').status_code == 422
