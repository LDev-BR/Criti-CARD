"""Add theme/work follows and creation time for new catalog works."""
from alembic import op
import sqlalchemy as sa

revision = '0016_discovery_follows'
down_revision = '0015_thematic_communities'
branch_labels = None
depends_on = None


def upgrade():
    identifier = sa.BigInteger().with_variant(sa.Integer(), 'sqlite')
    op.add_column('obras', sa.Column('created_at', sa.DateTime(timezone=True), nullable=True))
    op.create_table('work_follows',
        sa.Column('id', identifier, primary_key=True),
        sa.Column('user_id', identifier, sa.ForeignKey('usuarios.id', ondelete='CASCADE'), nullable=False),
        sa.Column('work_id', identifier, sa.ForeignKey('obras.id', ondelete='CASCADE'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('user_id','work_id',name='uq_work_follows_user_work'))
    op.create_index('ix_work_follows_work_id','work_follows',['work_id'])
    op.create_table('category_follows',
        sa.Column('id', identifier, primary_key=True),
        sa.Column('user_id', identifier, sa.ForeignKey('usuarios.id', ondelete='CASCADE'), nullable=False),
        sa.Column('category_id', identifier, sa.ForeignKey('categorias.id', ondelete='CASCADE'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('user_id','category_id',name='uq_category_follows_user_category'))
    op.create_index('ix_category_follows_category_id','category_follows',['category_id'])


def downgrade():
    op.drop_table('category_follows')
    op.drop_table('work_follows')
    op.drop_column('obras','created_at')
