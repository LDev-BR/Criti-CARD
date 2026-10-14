"""Private progression ledger and cosmetic grants; preserve legacy timestamps."""
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa

revision = '0012_progression'
down_revision = '0011_unique_cards'
branch_labels = None
depends_on = None


def upgrade():
    identifier = sa.BigInteger().with_variant(sa.Integer(),'sqlite')
    op.create_table('progression_profiles',
        sa.Column('user_id',identifier,sa.ForeignKey('usuarios.id',ondelete='CASCADE'),primary_key=True),
        sa.Column('xp',identifier,nullable=False,server_default='0'),
        sa.Column('membership_since',sa.DateTime(timezone=True),nullable=False),
        sa.Column('membership_origin',sa.String(16),nullable=False),
        sa.Column('is_pioneer',sa.Integer(),nullable=False,server_default='0'),
        sa.Column('history_imported_at',sa.DateTime(timezone=True)),
        sa.Column('notice_level',sa.Integer(),nullable=False,server_default='1'),
        sa.CheckConstraint('xp >= 0',name='ck_progression_xp'),
        sa.CheckConstraint('is_pioneer IN (0,1)',name='ck_progression_pioneer'),
        sa.CheckConstraint("membership_origin IN ('signup','rollout')",name='ck_progression_membership'))
    op.create_table('experience_events',
        sa.Column('id',identifier,primary_key=True),
        sa.Column('user_id',identifier,sa.ForeignKey('usuarios.id',ondelete='CASCADE'),nullable=False),
        sa.Column('event_key',sa.String(100),nullable=False),sa.Column('kind',sa.String(32),nullable=False),
        sa.Column('origin',sa.String(16),nullable=False),sa.Column('delta',sa.Integer(),nullable=False),
        sa.Column('work_id',identifier,sa.ForeignKey('obras.id',ondelete='SET NULL')),
        sa.Column('category_id',identifier,sa.ForeignKey('categorias.id',ondelete='SET NULL')),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.Column('quota_day',sa.String(10),nullable=False),sa.Column('rule_version',sa.Integer(),nullable=False),
        sa.Column('reason',sa.Text()),sa.Column('actor_id',identifier,sa.ForeignKey('usuarios.id',ondelete='SET NULL')),
        sa.Column('reverses_event_id',identifier,sa.ForeignKey('experience_events.id',ondelete='SET NULL')),
        sa.UniqueConstraint('user_id','event_key',name='uq_experience_origin'),
        sa.UniqueConstraint('reverses_event_id',name='uq_experience_reversal'),sqlite_autoincrement=True)
    op.create_index('ix_experience_quota','experience_events',['user_id','quota_day'])
    op.create_index('ix_experience_owner_id','experience_events',['user_id','id'])
    for name in ('achievement_grants','reward_grants'):
        op.create_table(name,
            sa.Column('user_id',identifier,sa.ForeignKey('usuarios.id',ondelete='CASCADE'),primary_key=True),
            sa.Column('slug',sa.String(80),primary_key=True),
            sa.Column('granted_at',sa.DateTime(timezone=True),nullable=False),
            sa.Column('revoked_at',sa.DateTime(timezone=True)),sa.Column('notice_seen_at',sa.DateTime(timezone=True)))
    connection = op.get_bind()
    users = sa.table('usuarios',sa.column('id'),sa.column('created_at',sa.DateTime(timezone=True)))
    profiles = sa.table('progression_profiles',sa.column('user_id'),sa.column('membership_since',sa.DateTime(timezone=True)),
        sa.column('membership_origin'),sa.column('is_pioneer'))
    rollout = datetime.now(timezone.utc)
    for user in connection.execute(sa.select(users.c.id,users.c.created_at)).mappings():
        connection.execute(profiles.insert().values(user_id=user['id'],membership_since=user['created_at'] or rollout,
            membership_origin='signup' if user['created_at'] else 'rollout',is_pioneer=1))


def downgrade():
    for table in ('reward_grants','achievement_grants','experience_events','progression_profiles'):
        op.drop_table(table)
