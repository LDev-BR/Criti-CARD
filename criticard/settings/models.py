"""One preference document per account, deleted with its owner."""
from sqlalchemy import DateTime, ForeignKey, JSON
from sqlalchemy.orm import mapped_column

from ..models import Base, ID, utcnow


class UserSettings(Base):
    __tablename__ = 'user_settings'
    user_id = mapped_column(ID, ForeignKey('usuarios.id', ondelete='CASCADE'), primary_key=True)
    preferences = mapped_column(JSON, nullable=False)
    updated_at = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
