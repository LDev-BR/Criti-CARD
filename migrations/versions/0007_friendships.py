"""Explicit friendship invitations, independent from directional follows."""
from alembic import op
import sqlalchemy as sa

revision = '0007_friendships'
down_revision = '0006_merge'
branch_labels = None
depends_on = None


def upgrade():
    identity = sa.BigInteger().with_variant(sa.Integer(), 'sqlite')
    op.create_table('friendships',
        sa.Column('id', identity, primary_key=True),
        sa.Column('user_low_id', identity, sa.ForeignKey('usuarios.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_high_id', identity, sa.ForeignKey('usuarios.id', ondelete='CASCADE'), nullable=False),
        sa.Column('requested_by', identity, sa.ForeignKey('usuarios.id', ondelete='CASCADE'), nullable=False),
        sa.Column('status', sa.String(16), nullable=False, server_default='pending'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('accepted_at', sa.DateTime(timezone=True)),
        sa.UniqueConstraint('user_low_id', 'user_high_id', name='uq_friendships_pair'),
        sa.CheckConstraint('user_low_id < user_high_id', name='ck_friendships_ordered_pair'),
        sa.CheckConstraint('requested_by IN (user_low_id, user_high_id)', name='ck_friendships_requester'),
        sa.CheckConstraint("status IN ('pending','accepted')", name='ck_friendships_status'),
        sqlite_autoincrement=True)
    op.create_index('ix_friendships_user_high_id', 'friendships', ['user_high_id'])


def downgrade():
    op.drop_table('friendships')
