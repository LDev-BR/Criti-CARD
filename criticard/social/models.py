"""Social tables share the application's declarative metadata."""
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import mapped_column

from ..models import Base, ID, utcnow


class WorkFollow(Base):
    __tablename__ = 'work_follows'
    __table_args__ = (UniqueConstraint('user_id', 'work_id', name='uq_work_follows_user_work'),)
    id = mapped_column(ID, primary_key=True)
    user_id = mapped_column(ID, ForeignKey('usuarios.id', ondelete='CASCADE'), nullable=False)
    work_id = mapped_column(ID, ForeignKey('obras.id', ondelete='CASCADE'), nullable=False, index=True)
    created_at = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class CategoryFollow(Base):
    __tablename__ = 'category_follows'
    __table_args__ = (UniqueConstraint('user_id', 'category_id', name='uq_category_follows_user_category'),)
    id = mapped_column(ID, primary_key=True)
    user_id = mapped_column(ID, ForeignKey('usuarios.id', ondelete='CASCADE'), nullable=False)
    category_id = mapped_column(ID, ForeignKey('categorias.id', ondelete='CASCADE'), nullable=False, index=True)
    created_at = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class CardLike(Base):
    __tablename__ = 'card_likes'
    __table_args__ = (UniqueConstraint('user_id', 'card_id', name='uq_card_likes_user_card'),)
    id = mapped_column(ID, primary_key=True)
    user_id = mapped_column(ID, ForeignKey('usuarios.id', ondelete='CASCADE'), nullable=False)
    card_id = mapped_column(ID, ForeignKey('cards.id', ondelete='CASCADE'), nullable=False, index=True)
    created_at = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class Comment(Base):
    __tablename__ = 'comments'
    __table_args__ = (CheckConstraint('length(body) BETWEEN 1 AND 2000', name='ck_comments_body_length'),
                     {'sqlite_autoincrement': True})
    id = mapped_column(ID, primary_key=True)
    author_id = mapped_column(ID, ForeignKey('usuarios.id', ondelete='CASCADE'), nullable=False, index=True)
    card_id = mapped_column(ID, ForeignKey('cards.id', ondelete='CASCADE'), nullable=False, index=True)
    body = mapped_column(Text, nullable=False)
    created_at = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class Follow(Base):
    __tablename__ = 'follows'
    __table_args__ = (UniqueConstraint('user_id', 'target_id', name='uq_follows_user_target'),
                     CheckConstraint('user_id <> target_id', name='ck_follows_not_self'))
    id = mapped_column(ID, primary_key=True)
    user_id = mapped_column(ID, ForeignKey('usuarios.id', ondelete='CASCADE'), nullable=False)
    target_id = mapped_column(ID, ForeignKey('usuarios.id', ondelete='CASCADE'), nullable=False, index=True)
    created_at = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class Block(Base):
    __tablename__ = 'blocks'
    __table_args__ = (UniqueConstraint('user_id', 'target_id', name='uq_blocks_user_target'),
                     CheckConstraint('user_id <> target_id', name='ck_blocks_not_self'))
    id = mapped_column(ID, primary_key=True)
    user_id = mapped_column(ID, ForeignKey('usuarios.id', ondelete='CASCADE'), nullable=False)
    target_id = mapped_column(ID, ForeignKey('usuarios.id', ondelete='CASCADE'), nullable=False, index=True)
    created_at = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class Friend(Base):
    __tablename__ = 'friendships'
    __table_args__ = (
        UniqueConstraint('user_low_id', 'user_high_id', name='uq_friendships_pair'),
        CheckConstraint('user_low_id < user_high_id', name='ck_friendships_ordered_pair'),
        CheckConstraint('requested_by IN (user_low_id, user_high_id)', name='ck_friendships_requester'),
        CheckConstraint("status IN ('pending','accepted')", name='ck_friendships_status'),
        {'sqlite_autoincrement': True})
    id = mapped_column(ID, primary_key=True)
    user_low_id = mapped_column(ID, ForeignKey('usuarios.id', ondelete='CASCADE'), nullable=False)
    user_high_id = mapped_column(ID, ForeignKey('usuarios.id', ondelete='CASCADE'), nullable=False, index=True)
    requested_by = mapped_column(ID, ForeignKey('usuarios.id', ondelete='CASCADE'), nullable=False)
    status = mapped_column(String(16), nullable=False, default='pending', server_default='pending')
    created_at = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    accepted_at = mapped_column(DateTime(timezone=True))


class Notification(Base):
    __tablename__ = 'notifications'
    __table_args__ = (UniqueConstraint('event_key', name='uq_notifications_event_key'),)
    id = mapped_column(ID, primary_key=True)
    recipient_id = mapped_column(ID, ForeignKey('usuarios.id', ondelete='CASCADE'), nullable=False, index=True)
    actor_id = mapped_column(ID, ForeignKey('usuarios.id', ondelete='SET NULL'))
    kind = mapped_column(String(32), nullable=False)
    card_id = mapped_column(ID, ForeignKey('cards.id', ondelete='CASCADE'))
    comment_id = mapped_column(ID, ForeignKey('comments.id', ondelete='SET NULL'))
    event_key = mapped_column(String(180), nullable=False)
    created_at = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    read_at = mapped_column(DateTime(timezone=True))


class Report(Base):
    __tablename__ = 'reports'
    __table_args__ = (CheckConstraint("target_type IN ('card','comment','user','chat_message','community_post','community_comment')", name='ck_reports_target_type'),
                     CheckConstraint("status IN ('pending','resolved')", name='ck_reports_status'),
                     CheckConstraint('length(reason) BETWEEN 1 AND 2000', name='ck_reports_reason_length'))
    id = mapped_column(ID, primary_key=True)
    reporter_id = mapped_column(ID, ForeignKey('usuarios.id', ondelete='SET NULL'))
    target_type = mapped_column(String(24), nullable=False)
    target_id = mapped_column(ID, nullable=False)
    reason = mapped_column(Text, nullable=False)
    status = mapped_column(String(16), nullable=False, default='pending', server_default='pending')
    created_at = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    resolved_at = mapped_column(DateTime(timezone=True))
    resolved_by = mapped_column(ID, ForeignKey('usuarios.id', ondelete='SET NULL'))
