"""Persistent private conversations, receipts, messages and send limits."""
from sqlalchemy import CheckConstraint, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.orm import mapped_column

from criticard.models import Base, ID, utcnow


class Conversation(Base):
    __tablename__ = 'conversations'
    __table_args__ = (
        UniqueConstraint('pair_low_id', 'pair_high_id', name='uq_conversations_pair'),
        CheckConstraint('pair_low_id < pair_high_id', name='ck_conversations_pair_order'),
    )
    id = mapped_column(ID, primary_key=True)
    pair_low_id = mapped_column(ID, ForeignKey('usuarios.id', ondelete='SET NULL'))
    pair_high_id = mapped_column(ID, ForeignKey('usuarios.id', ondelete='SET NULL'))
    kind = mapped_column(String(16), nullable=False, default='direct', server_default='direct')
    created_at = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class Message(Base):
    __tablename__ = 'messages'
    __table_args__ = (
        UniqueConstraint('sender_id', 'conversation_id', 'client_nonce', name='uq_messages_sender_nonce'),
        CheckConstraint('length(body) BETWEEN 1 AND 2000', name='ck_messages_body_length'),
        Index('ix_messages_conversation_id_id', 'conversation_id', 'id'),
    )
    id = mapped_column(ID, primary_key=True)
    conversation_id = mapped_column(ID, ForeignKey('conversations.id', ondelete='CASCADE'), nullable=False)
    sender_id = mapped_column(ID, ForeignKey('usuarios.id', ondelete='SET NULL'))
    redacted_at = mapped_column(DateTime(timezone=True))
    redacted_by = mapped_column(ID, ForeignKey('usuarios.id', ondelete='SET NULL'))
    body = mapped_column(Text, nullable=False)
    client_nonce = mapped_column(String(36), nullable=False)
    created_at = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class ConversationMember(Base):
    __tablename__ = 'conversation_members'
    __table_args__ = (Index('ix_conversation_members_user_id', 'user_id', 'conversation_id'),)
    conversation_id = mapped_column(ID, ForeignKey('conversations.id', ondelete='CASCADE'), primary_key=True)
    user_id = mapped_column(ID, ForeignKey('usuarios.id', ondelete='CASCADE'), primary_key=True)
    last_read_id = mapped_column(ID, ForeignKey('messages.id', ondelete='SET NULL'))
    role = mapped_column(String(16), nullable=False, default='member', server_default='member')
    joined_at = mapped_column(DateTime(timezone=True), default=utcnow,
        server_default=text('CURRENT_TIMESTAMP'))


class GroupChat(Base):
    __tablename__ = 'group_chats'
    __table_args__ = (
        UniqueConstraint('slug', name='uq_group_chats_slug'),
        CheckConstraint("mode IN ('open','closed')", name='ck_group_chats_mode'),
        CheckConstraint('minimum_level >= 1', name='ck_group_chats_minimum_level'),
        CheckConstraint('archived IN (0,1)', name='ck_group_chats_archived'),
        Index('ix_group_chats_discovery','archived','created_at'),
    )
    conversation_id = mapped_column(ID, ForeignKey('conversations.id', ondelete='CASCADE'), primary_key=True)
    owner_id = mapped_column(ID, ForeignKey('usuarios.id', ondelete='SET NULL'))
    creator_id = mapped_column(ID, ForeignKey('usuarios.id', ondelete='SET NULL'))
    name = mapped_column(String(60), nullable=False)
    slug = mapped_column(String(80), nullable=False)
    description = mapped_column(String(500), nullable=False, default='', server_default='')
    mode = mapped_column(String(16), nullable=False)
    minimum_level = mapped_column(Integer, nullable=False, default=1, server_default='1')
    visual_token = mapped_column(String(24), nullable=False, default='gold', server_default='gold')
    archived = mapped_column(Integer, nullable=False, default=0, server_default='0')
    created_at = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class GroupJoinRequest(Base):
    __tablename__ = 'group_join_requests'
    __table_args__ = (
        CheckConstraint("status IN ('pending','approved','denied','cancelled')", name='ck_group_join_requests_status'),
        Index('uq_group_join_requests_pending', 'conversation_id', 'user_id', unique=True,
            sqlite_where=text("status = 'pending'"), postgresql_where=text("status = 'pending'")),
        Index('ix_group_join_requests_group_status', 'conversation_id', 'status', 'created_at'),
        {'sqlite_autoincrement': True},
    )
    id = mapped_column(ID, primary_key=True)
    conversation_id = mapped_column(ID, ForeignKey('conversations.id', ondelete='CASCADE'), nullable=False)
    user_id = mapped_column(ID, ForeignKey('usuarios.id', ondelete='CASCADE'), nullable=False)
    status = mapped_column(String(16), nullable=False, default='pending', server_default='pending')
    created_at = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    resolved_at = mapped_column(DateTime(timezone=True))
    resolved_by = mapped_column(ID, ForeignKey('usuarios.id', ondelete='SET NULL'))


class GroupInvite(Base):
    __tablename__ = 'group_invites'
    __table_args__ = (
        CheckConstraint("status IN ('pending','accepted','declined','cancelled')", name='ck_group_invites_status'),
        Index('uq_group_invites_pending', 'conversation_id', 'invitee_id', unique=True,
            sqlite_where=text("status = 'pending'"), postgresql_where=text("status = 'pending'")),
        Index('ix_group_invites_invitee_status', 'invitee_id', 'status', 'created_at'),
        {'sqlite_autoincrement': True},
    )
    id = mapped_column(ID, primary_key=True)
    conversation_id = mapped_column(ID, ForeignKey('conversations.id', ondelete='CASCADE'), nullable=False)
    inviter_id = mapped_column(ID, ForeignKey('usuarios.id', ondelete='CASCADE'), nullable=False)
    invitee_id = mapped_column(ID, ForeignKey('usuarios.id', ondelete='CASCADE'), nullable=False)
    status = mapped_column(String(16), nullable=False, default='pending', server_default='pending')
    created_at = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    resolved_at = mapped_column(DateTime(timezone=True))


class ChatRateAttempt(Base):
    __tablename__ = 'chat_rate_attempts'
    user_id = mapped_column(ID, ForeignKey('usuarios.id', ondelete='CASCADE'), primary_key=True)
    attempts = mapped_column(Integer, nullable=False)
    expires = mapped_column(Float, nullable=False)
