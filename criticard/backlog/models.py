"""Collection persistence and database-enforced invariants."""
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import mapped_column

from criticard.models import Base, ID, utcnow


class BacklogItem(Base):
    __tablename__ = "backlog_items"
    __table_args__ = (
        UniqueConstraint("user_id", "work_id", name="uq_backlog_user_work"),
        CheckConstraint("status IN ('planned','in_progress','completed','paused','dropped')", name="ck_backlog_status"),
        CheckConstraint("visibility IN ('private','public')", name="ck_backlog_visibility"),
        CheckConstraint("progress IS NULL OR (progress >= 0 AND progress <= 100000)", name="ck_backlog_progress"),
        CheckConstraint("progress_unit IS NULL OR progress_unit IN ('hours','episodes','chapters')", name="ck_backlog_progress_unit"),
        Index("ix_backlog_user_status", "user_id", "status"),
        Index("ix_backlog_user_visibility", "user_id", "visibility"),
        Index("ix_backlog_work", "work_id"),
    )
    id = mapped_column(ID, primary_key=True)
    user_id = mapped_column(ID, ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False)
    work_id = mapped_column(ID, ForeignKey("obras.id", ondelete="CASCADE"), nullable=False)
    status = mapped_column(String(20), nullable=False, server_default="planned")
    visibility = mapped_column(String(10), nullable=False, server_default="private")
    progress = mapped_column(Integer)
    progress_unit = mapped_column(String(12))
    created_at = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now(), nullable=False)
    updated_at = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now(), nullable=False)
