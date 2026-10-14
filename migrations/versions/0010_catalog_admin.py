"""Additive catalog availability; historical identifiers and references stay intact."""
from alembic import op
import sqlalchemy as sa

revision = '0010_catalog_admin'
down_revision = '0009_privacy_requests'
branch_labels = None
depends_on = None


def upgrade():
    # An inline check permits SQLite's additive ALTER TABLE without rebuilding
    # a catalog table referenced by existing cards and collection items.
    op.add_column('obras', sa.Column('active', sa.Integer(),
        sa.CheckConstraint('active IN (0,1)', name='ck_obras_active'),
        nullable=False, server_default='1'))
    op.create_index('ix_obras_active', 'obras', ['active'])


def downgrade():
    op.drop_index('ix_obras_active', table_name='obras')
    with op.batch_alter_table('obras') as batch:
        batch.drop_constraint('ck_obras_active', type_='check')
        batch.drop_column('active')
