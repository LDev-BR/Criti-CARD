"""Hashed single-use links tied to an exact account state."""
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import mapped_column

from criticard.models import Base, ID, utcnow


class AccountToken(Base):
    __tablename__ = "account_tokens"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_account_token_hash"),
        CheckConstraint("purpose IN ('reset','verify')", name="ck_account_token_purpose"),
        Index("ix_account_token_user_purpose", "user_id", "purpose"),
        Index("ix_account_token_expiry", "expires_at"),
    )
    id = mapped_column(ID, primary_key=True)
    user_id = mapped_column(ID, ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False)
    token_hash = mapped_column(String(64), nullable=False)
    purpose = mapped_column(String(8), nullable=False)
    email_snapshot = mapped_column(Text, nullable=False)
    session_version = mapped_column(Integer, nullable=False)
    created_at = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now(), nullable=False)
    expires_at = mapped_column(DateTime(timezone=True), nullable=False)
    used_at = mapped_column(DateTime(timezone=True))
