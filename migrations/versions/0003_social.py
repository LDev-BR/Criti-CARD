"""Likes, comments, follows, blocks, notifications and reports."""
from alembic import op
import sqlalchemy as sa

revision = '0003_social'
down_revision = '0001_core'
branch_labels = ('social',)
depends_on = None


def upgrade():
    identity = sa.BigInteger().with_variant(sa.Integer(), 'sqlite')
    def pk():
        return sa.Column('id', identity, primary_key=True)
    def user(name, ondelete='CASCADE', nullable=False):
        return sa.Column(name, identity, sa.ForeignKey('usuarios.id', ondelete=ondelete), nullable=nullable)
    def created():
        return sa.Column('created_at', sa.DateTime(timezone=True), nullable=False)
    op.create_table('card_likes', pk(), user('user_id'),
        sa.Column('card_id', identity, sa.ForeignKey('cards.id', ondelete='CASCADE'), nullable=False), created(),
        sa.UniqueConstraint('user_id', 'card_id', name='uq_card_likes_user_card'))
    op.create_index('ix_card_likes_card_id', 'card_likes', ['card_id'])
    op.create_table('comments', pk(), user('author_id'),
        sa.Column('card_id', identity, sa.ForeignKey('cards.id', ondelete='CASCADE'), nullable=False),
        sa.Column('body', sa.Text(), nullable=False), created(),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint('length(body) BETWEEN 1 AND 2000', name='ck_comments_body_length'), sqlite_autoincrement=True)
    op.create_index('ix_comments_author_id', 'comments', ['author_id'])
    op.create_index('ix_comments_card_id', 'comments', ['card_id'])
    op.create_table('follows', pk(), user('user_id'), user('target_id'), created(),
        sa.UniqueConstraint('user_id', 'target_id', name='uq_follows_user_target'),
        sa.CheckConstraint('user_id <> target_id', name='ck_follows_not_self'))
    op.create_index('ix_follows_target_id', 'follows', ['target_id'])
    op.create_table('blocks', pk(), user('user_id'), user('target_id'), created(),
        sa.UniqueConstraint('user_id', 'target_id', name='uq_blocks_user_target'),
        sa.CheckConstraint('user_id <> target_id', name='ck_blocks_not_self'))
    op.create_index('ix_blocks_target_id', 'blocks', ['target_id'])
    op.create_table('notifications', pk(), user('recipient_id'), user('actor_id', 'SET NULL', True),
        sa.Column('kind', sa.String(32), nullable=False),
        sa.Column('card_id', identity, sa.ForeignKey('cards.id', ondelete='CASCADE')),
        sa.Column('comment_id', identity, sa.ForeignKey('comments.id', ondelete='SET NULL')),
        sa.Column('event_key', sa.String(180), nullable=False), created(),
        sa.Column('read_at', sa.DateTime(timezone=True)),
        sa.UniqueConstraint('event_key', name='uq_notifications_event_key'))
    op.create_index('ix_notifications_recipient_id', 'notifications', ['recipient_id'])
    op.create_table('reports', pk(), user('reporter_id', 'SET NULL', True),
        sa.Column('target_type', sa.String(16), nullable=False),
        sa.Column('target_id', identity, nullable=False), sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('status', sa.String(16), nullable=False, server_default='pending'), created(),
        sa.Column('resolved_at', sa.DateTime(timezone=True)), user('resolved_by', 'SET NULL', True),
        sa.CheckConstraint("target_type IN ('card','comment','user')", name='ck_reports_target_type'),
        sa.CheckConstraint("status IN ('pending','resolved')", name='ck_reports_status'),
        sa.CheckConstraint('length(reason) BETWEEN 1 AND 2000', name='ck_reports_reason_length'))


def downgrade():
    for table in ('reports', 'notifications', 'blocks', 'follows', 'comments', 'card_likes'):
        op.drop_table(table)
