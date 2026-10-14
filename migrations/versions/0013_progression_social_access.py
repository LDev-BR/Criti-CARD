"""Persist social contribution time and preserve active rollout cosmetics."""
from alembic import op
import sqlalchemy as sa

revision = '0013_progression_social_access'
down_revision = '0012_progression'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('progression_profiles',
        sa.Column('first_contribution_at', sa.DateTime(timezone=True), nullable=True))
    for table in ('achievement_grants', 'reward_grants'):
        op.add_column(table, sa.Column('legacy_protected', sa.Integer(), nullable=False, server_default='0'))

    connection = op.get_bind()
    events = sa.table('experience_events',
        sa.column('id', sa.BigInteger()), sa.column('user_id', sa.BigInteger()),
        sa.column('kind', sa.String()), sa.column('origin', sa.String()),
        sa.column('created_at', sa.DateTime(timezone=True)),
        sa.column('reverses_event_id', sa.BigInteger()))
    profiles = sa.table('progression_profiles', sa.column('user_id', sa.BigInteger()),
        sa.column('first_contribution_at', sa.DateTime(timezone=True)))
    reversals = sa.select(events.c.reverses_event_id).where(events.c.reverses_event_id.is_not(None))
    first_at = sa.select(sa.func.min(events.c.created_at)).where(
        events.c.user_id == profiles.c.user_id, events.c.origin == 'live',
        events.c.kind.in_(('card_published', 'work_completed', 'weekly_activity')),
        events.c.id.not_in(reversals)).scalar_subquery()
    connection.execute(profiles.update().where(profiles.c.first_contribution_at.is_(None),
        first_at.is_not(None)).values(first_contribution_at=first_at))

    grants = sa.table('reward_grants', sa.column('revoked_at'), sa.column('legacy_protected'))
    achievements = sa.table('achievement_grants', sa.column('slug'), sa.column('revoked_at'),
        sa.column('legacy_protected'))
    connection.execute(grants.update().where(grants.c.revoked_at.is_(None)).values(legacy_protected=1))
    connection.execute(achievements.update().where(achievements.c.revoked_at.is_(None),
        achievements.c.slug.like('level_%')).values(legacy_protected=1))


def downgrade():
    for table in ('achievement_grants', 'reward_grants'):
        op.drop_column(table, 'legacy_protected')
    op.drop_column('progression_profiles', 'first_contribution_at')
