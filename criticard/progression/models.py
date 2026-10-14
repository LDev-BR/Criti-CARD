from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import mapped_column

from ..models import Base, ID, utcnow


class ProgressionProfile(Base):
    __tablename__ = 'progression_profiles'
    __table_args__ = (CheckConstraint('xp >= 0',name='ck_progression_xp'),
        CheckConstraint('is_pioneer IN (0,1)',name='ck_progression_pioneer'),
        CheckConstraint("membership_origin IN ('signup','rollout')",name='ck_progression_membership'))
    user_id = mapped_column(ID,ForeignKey('usuarios.id',ondelete='CASCADE'),primary_key=True)
    xp = mapped_column(ID,nullable=False,server_default='0')
    membership_since = mapped_column(DateTime(timezone=True),nullable=False)
    membership_origin = mapped_column(String(16),nullable=False)
    is_pioneer = mapped_column(Integer,nullable=False,server_default='0')
    history_imported_at = mapped_column(DateTime(timezone=True))
    first_contribution_at = mapped_column(DateTime(timezone=True))
    notice_level = mapped_column(Integer,nullable=False,server_default='1')


class ExperienceEvent(Base):
    __tablename__ = 'experience_events'
    __table_args__ = (UniqueConstraint('user_id','event_key',name='uq_experience_origin'),
        UniqueConstraint('reverses_event_id',name='uq_experience_reversal'),
        Index('ix_experience_quota','user_id','quota_day'),Index('ix_experience_owner_id','user_id','id'),
        {'sqlite_autoincrement':True})
    id = mapped_column(ID,primary_key=True)
    user_id = mapped_column(ID,ForeignKey('usuarios.id',ondelete='CASCADE'),nullable=False)
    event_key = mapped_column(String(100),nullable=False)
    kind = mapped_column(String(32),nullable=False)
    origin = mapped_column(String(16),nullable=False)
    delta = mapped_column(Integer,nullable=False)
    work_id = mapped_column(ID,ForeignKey('obras.id',ondelete='SET NULL'))
    category_id = mapped_column(ID,ForeignKey('categorias.id',ondelete='SET NULL'))
    created_at = mapped_column(DateTime(timezone=True),nullable=False,default=utcnow)
    quota_day = mapped_column(String(10),nullable=False)
    rule_version = mapped_column(Integer,nullable=False)
    reason = mapped_column(Text)
    actor_id = mapped_column(ID,ForeignKey('usuarios.id',ondelete='SET NULL'))
    reverses_event_id = mapped_column(ID,ForeignKey('experience_events.id',ondelete='SET NULL'))


class AchievementGrant(Base):
    __tablename__ = 'achievement_grants'
    user_id = mapped_column(ID,ForeignKey('usuarios.id',ondelete='CASCADE'),primary_key=True)
    slug = mapped_column(String(80),primary_key=True)
    granted_at = mapped_column(DateTime(timezone=True),nullable=False,default=utcnow)
    revoked_at = mapped_column(DateTime(timezone=True))
    notice_seen_at = mapped_column(DateTime(timezone=True))
    legacy_protected = mapped_column(Integer,nullable=False,server_default='0')


class RewardGrant(Base):
    __tablename__ = 'reward_grants'
    user_id = mapped_column(ID,ForeignKey('usuarios.id',ondelete='CASCADE'),primary_key=True)
    slug = mapped_column(String(80),primary_key=True)
    granted_at = mapped_column(DateTime(timezone=True),nullable=False,default=utcnow)
    revoked_at = mapped_column(DateTime(timezone=True))
    notice_seen_at = mapped_column(DateTime(timezone=True))
    legacy_protected = mapped_column(Integer,nullable=False,server_default='0')
