"""One published review per author/work, preserving previous duplicates privately."""
from alembic import op
import sqlalchemy as sa

revision = '0011_unique_cards'
down_revision = '0010_catalog_admin'
branch_labels = None
depends_on = None


def upgrade():
    policy = op.get_context().config.attributes.get('keep_duplicate_review', 'latest')
    if policy not in {'latest', 'oldest'}:
        raise ValueError('Invalid historical review preference')
    op.add_column('cards', sa.Column('archived', sa.Integer(),
        sa.CheckConstraint('archived IN (0,1)', name='ck_cards_archived'),
        nullable=False, server_default='0'))
    cards = sa.table('cards', sa.column('id'), sa.column('author_id'),
        sa.column('obra_id'), sa.column('archived'))
    preferred = cards.alias('preferred')
    comparison = preferred.c.id > cards.c.id if policy == 'latest' else preferred.c.id < cards.c.id
    # Archive only duplicate published rows. Keep IDs, text, timestamps,
    # images, likes, comments and notifications exactly as they were.
    op.get_bind().execute(cards.update().where(cards.c.obra_id.is_not(None),
        sa.exists(sa.select(1).where(preferred.c.author_id == cards.c.author_id,
            preferred.c.obra_id == cards.c.obra_id, comparison))).values(archived=1))
    op.create_index('uq_cards_author_work_published', 'cards', ['author_id', 'obra_id'],
        unique=True, sqlite_where=sa.text('archived = 0'), postgresql_where=sa.text('archived = 0'))


def downgrade():
    op.drop_index('uq_cards_author_work_published', table_name='cards')
    with op.batch_alter_table('cards') as batch:
        batch.drop_constraint('ck_cards_archived', type_='check')
        batch.drop_column('archived')
