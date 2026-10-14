"""Requests belong to their account; replies keep an append-only history."""
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import mapped_column

from criticard.models import Base, ID, utcnow


class PrivacyRequest(Base):
    __tablename__ = 'privacy_requests'
    __table_args__ = (
        UniqueConstraint('protocol', name='uq_privacy_requests_protocol'),
        CheckConstraint("kind IN ('access','correction','deletion','portability','sharing','consent','objection','other')",
            name='ck_privacy_requests_kind'),
        CheckConstraint("status IN ('received','in_review','answered')", name='ck_privacy_requests_status'),
        CheckConstraint('length(body) BETWEEN 1 AND 3000', name='ck_privacy_requests_body_length'),
        Index('ix_privacy_requests_user_created', 'user_id', 'created_at'),
        {'sqlite_autoincrement': True})
    id = mapped_column(ID, primary_key=True)
    protocol = mapped_column(String(35), nullable=False)
    user_id = mapped_column(ID, ForeignKey('usuarios.id', ondelete='CASCADE'), nullable=False)
    kind = mapped_column(String(16), nullable=False)
    body = mapped_column(Text, nullable=False)
    status = mapped_column(String(16), nullable=False, default='received', server_default='received')
    created_at = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class PrivacyReply(Base):
    __tablename__ = 'privacy_replies'
    __table_args__ = (
        CheckConstraint("status IN ('received','in_review','answered')", name='ck_privacy_replies_status'),
        CheckConstraint('length(body) BETWEEN 1 AND 3000', name='ck_privacy_replies_body_length'),
        {'sqlite_autoincrement': True})
    id = mapped_column(ID, primary_key=True)
    request_id = mapped_column(ID, ForeignKey('privacy_requests.id', ondelete='CASCADE'), nullable=False, index=True)
    responder_id = mapped_column(ID, ForeignKey('usuarios.id', ondelete='SET NULL'))
    body = mapped_column(Text, nullable=False)
    status = mapped_column(String(16), nullable=False)
    created_at = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class PendingImageDeletion(Base):
    """Keep failed storage work retryable without retaining the deleted account."""
    __tablename__ = 'pending_image_deletions'
    __table_args__ = (
        UniqueConstraint('kind', 'filename', name='uq_pending_image_deletions_file'),
        CheckConstraint("kind IN ('avatar','cover')", name='ck_pending_image_deletions_kind'))
    id = mapped_column(ID, primary_key=True)
    kind = mapped_column(String(8), nullable=False)
    filename = mapped_column(String(255), nullable=False)
    created_at = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
