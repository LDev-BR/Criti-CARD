"""Conversation lists stay private and bounded as memberships grow."""
from contextlib import contextmanager
from datetime import datetime, timezone
from uuid import UUID

import pytest
from sqlalchemy import delete, event, insert, update

from criticard.chat.models import (Conversation, ConversationMember, GroupChat,
    GroupJoinRequest, Message)
from criticard.chat.service import ChatError, conversation_summary, conversations
from criticard.db import get_db
from criticard.models import User
from criticard.social.models import Block
from test_chat import app


CREATED_AT = datetime(2026, 1, 1, tzinfo=timezone.utc)


def add_user(db, user_id):
    db.execute(insert(User).values(id=user_id, username=f'PEER{user_id}',
        nome=f'Peer {user_id}', apelido='Leitor', about='Test profile',
        email=f'peer{user_id}@example.com', senha='unused'))


def add_direct(db, conversation_id, peer_id, owner_id=1):
    low, high = sorted((owner_id, peer_id))
    db.execute(insert(Conversation).values(id=conversation_id, pair_low_id=low,
        pair_high_id=high, created_at=CREATED_AT))
    db.execute(insert(ConversationMember), [
        {'conversation_id': conversation_id, 'user_id': owner_id},
        {'conversation_id': conversation_id, 'user_id': peer_id}])


def add_message(db, message_id, conversation_id, sender_id, body, *, redacted=False):
    db.execute(insert(Message).values(id=message_id, conversation_id=conversation_id,
        sender_id=sender_id, body=body, client_nonce=str(UUID(int=message_id)), created_at=CREATED_AT,
        redacted_at=CREATED_AT if redacted else None))


def add_group(db, conversation_id, owner_id, members, *, archived=False):
    db.execute(insert(Conversation).values(id=conversation_id, kind='group', created_at=CREATED_AT))
    db.execute(insert(GroupChat).values(conversation_id=conversation_id, owner_id=owner_id,
        creator_id=owner_id, name=f'Group {conversation_id}', slug=f'group-{conversation_id}',
        description='Private group description', mode='closed', visual_token='ocean',
        minimum_level=6, archived=int(archived), created_at=CREATED_AT, updated_at=CREATED_AT))
    db.execute(insert(ConversationMember), [
        {'conversation_id': conversation_id, 'user_id': user_id, 'role': role}
        for user_id, role in members])


@contextmanager
def counted_statements(engine):
    statements = []

    def capture(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(engine, 'before_cursor_execute', capture)
    try:
        yield statements
    finally:
        event.remove(engine, 'before_cursor_execute', capture)


@pytest.mark.parametrize('conversation_count', [1, 11])
def test_direct_conversation_list_uses_bounded_queries(app, conversation_count):
    with app.app_context():
        db = get_db()
        with db:
            for conversation_id in range(1, conversation_count + 1):
                peer_id = conversation_id + 1
                if peer_id > 3:
                    add_user(db, peer_id)
                add_direct(db, conversation_id, peer_id)
                add_message(db, conversation_id, conversation_id, peer_id, f'Message {conversation_id}')

        with counted_statements(app.extensions['database_engine']) as statements:
            data = conversations(1)

        assert [item['id'] for item in data['conversations']] == list(range(conversation_count, 0, -1))
        assert data['unread_count'] == conversation_count
        assert all(item['last_message']['body'] == f'Message {item["id"]}' for item in data['conversations'])
        assert len(statements) <= 6, f'{len(statements)} SQL statements for {conversation_count} conversations'


def test_direct_list_preserves_receipts_deleted_peers_blocks_and_empty_order(app):
    with app.app_context():
        db = get_db()
        with db:
            for user_id in range(4, 10):
                add_user(db, user_id)
            for conversation_id, peer_id in [(10, 2), (11, 3), (12, 4), (13, 5),
                    (14, 6), (16, 7), (17, 8)]:
                add_direct(db, conversation_id, peer_id)
            add_direct(db, 99, 9, owner_id=2)
            add_message(db, 100, 10, 2, 'Already read')
            add_message(db, 101, 10, 1, 'Own reply')
            add_message(db, 102, 10, None, 'Legacy anonymous sender')
            add_message(db, 103, 10, 2, 'Private redacted text', redacted=True)
            add_message(db, 104, 11, 1, 'Own latest message')
            add_message(db, 105, 12, 4, 'Legacy deleted sender')
            add_message(db, 200, 13, 5, 'Blocked outgoing')
            add_message(db, 201, 14, 6, 'Blocked incoming')
            add_message(db, 999, 99, 9, 'Other people only')
            db.execute(update(ConversationMember).where(ConversationMember.conversation_id == 10,
                ConversationMember.user_id == 1).values(last_read_id=100))
            db.execute(update(User).where(User.id == 3).values(active=0))
            db.execute(delete(User).where(User.id == 4))
            db.execute(insert(Block), [{'user_id': 1, 'target_id': 5}, {'user_id': 6, 'target_id': 1}])

        data = conversations(1)

    assert [item['id'] for item in data['conversations']] == [12, 11, 10, 17, 16]
    assert data['unread_count'] == 3
    items = {item['id']: item for item in data['conversations']}
    assert items[12]['peer'] is None
    assert items[12]['last_message']['sender'] is None
    assert items[12]['unread_count'] == 1
    assert items[11]['peer'] == {'id': 3, 'username': 'ADMIN', 'name': 'Admin',
        'avatar_url': '/static/default-avatar.svg'}
    assert items[11]['unread_count'] == 0
    assert items[10]['kind'] == 'direct' and items[10]['group'] is None
    assert items[10]['last_read_id'] == 100
    assert items[10]['unread_count'] == 2
    assert items[10]['peer'] == {'id': 2, 'username': 'BOB', 'name': 'Bob',
        'avatar_url': '/static/default-avatar.svg'}
    assert items[10]['last_message'] == {
        'id': 103, 'conversation_id': 10, 'body': 'Mensagem removida pela moderação.',
        'redacted': True, 'client_nonce': '00000000-0000-0000-0000-000000000067',
        'created_at': '2026-01-01T00:00:00+00:00',
        'sender': {'id': 2, 'username': 'BOB', 'name': 'Bob'}}
    assert items[17]['last_message'] is None and items[17]['unread_count'] == 0
    assert items[16]['last_message'] is None and items[16]['unread_count'] == 0
    assert 'email' not in str(data) and 'senha' not in str(data)
    assert 'Other people only' not in str(data) and 'Private redacted text' not in str(data)


def test_group_list_omits_archives_and_preserves_member_summary_privacy(app):
    with app.app_context():
        db = get_db()
        with db:
            add_user(db, 4)
            db.execute(update(User).where(User.id == 3).values(active=0))
            add_group(db, 40, 2, [(1, 'moderator'), (2, 'owner'), (3, 'member')])
            add_group(db, 41, 1, [(1, 'owner')])
            add_group(db, 42, 2, [(1, 'member'), (2, 'owner')], archived=True)
            add_group(db, 43, 2, [(2, 'owner')])
            add_direct(db, 10, 4)
            add_message(db, 299, 10, 4, 'Visible direct message')
            add_message(db, 300, 40, None, 'Anonymous group message')
            add_message(db, 301, 41, 1, 'Own group message')
            add_message(db, 302, 42, 2, 'Archived group message')
            add_message(db, 303, 43, 2, 'Nonmember group message')
            db.execute(insert(GroupJoinRequest).values(conversation_id=40, user_id=4,
                status='pending', created_at=CREATED_AT))

        with counted_statements(app.extensions['database_engine']) as statements:
            data = conversations(1)
        with pytest.raises(ChatError) as archived_error:
            conversation_summary(1, 42)
        assert archived_error.value.status == 404

    assert [item['id'] for item in data['conversations']] == [41, 40, 10]
    assert data['unread_count'] == 2
    items = {item['id']: item for item in data['conversations']}
    moderator_group = items[40]['group']
    assert items[40]['kind'] == 'group' and items[40]['peer'] is None
    assert moderator_group['name'] == 'Group 40'
    assert moderator_group['slug'] == 'group-40'
    assert moderator_group['description'] == 'Private group description'
    assert moderator_group['mode'] == 'closed' and moderator_group['minimum_level'] == 6
    assert moderator_group['visual_token'] == 'ocean'
    assert moderator_group['owner_id'] == 2 and not moderator_group['is_owner']
    assert moderator_group['role'] == 'moderator' and moderator_group['member_count'] == 2
    assert moderator_group['archived'] is False
    assert moderator_group['members'] == [] and moderator_group['pending_requests'] == []
    assert items[41]['group']['role'] == 'owner' and items[41]['group']['is_owner']
    assert items[41]['group']['member_count'] == 1 and items[41]['unread_count'] == 0
    assert len(statements) <= 6, f'{len(statements)} SQL statements for group conversations'
    assert 'Archived group message' not in str(data) and 'Nonmember group message' not in str(data)
