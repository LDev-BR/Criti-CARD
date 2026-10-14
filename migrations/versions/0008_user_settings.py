"""Account-scoped preferences, preserving all existing data."""
from alembic import op
import sqlalchemy as sa

revision = '0008_user_settings'
down_revision = '0007_friendships'
branch_labels = None
depends_on = None


def upgrade():
    identity = sa.BigInteger().with_variant(sa.Integer(), 'sqlite')
    op.create_table('user_settings',
        sa.Column('user_id', identity, sa.ForeignKey('usuarios.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('preferences', sa.JSON(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False))


def downgrade():
    op.drop_table('user_settings')
