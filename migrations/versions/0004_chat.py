"""Private chat and persistent rate limits (frozen schema)."""
from alembic import op
import sqlalchemy as sa

revision = '0004_chat'
down_revision = '0001_core'
branch_labels = ('chat',)
depends_on = None


def upgrade():
    identity = sa.BigInteger().with_variant(sa.Integer(), 'sqlite')
    op.create_table('conversations',
        sa.Column('id', identity, primary_key=True),
        sa.Column('pair_low_id', identity, sa.ForeignKey('usuarios.id', ondelete='SET NULL')),
        sa.Column('pair_high_id', identity, sa.ForeignKey('usuarios.id', ondelete='SET NULL')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('pair_low_id', 'pair_high_id', name='uq_conversations_pair'),
        sa.CheckConstraint('pair_low_id < pair_high_id', name='ck_conversations_pair_order'))
    op.create_table('messages',
        sa.Column('id', identity, primary_key=True),
        sa.Column('conversation_id', identity, sa.ForeignKey('conversations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('sender_id', identity, sa.ForeignKey('usuarios.id', ondelete='SET NULL')),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('client_nonce', sa.String(36), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('sender_id', 'conversation_id', 'client_nonce', name='uq_messages_sender_nonce'),
        sa.CheckConstraint('length(body) BETWEEN 1 AND 2000', name='ck_messages_body_length'))
    op.create_index('ix_messages_conversation_id_id', 'messages', ['conversation_id', 'id'])
    op.create_table('conversation_members',
        sa.Column('conversation_id', identity, sa.ForeignKey('conversations.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('user_id', identity, sa.ForeignKey('usuarios.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('last_read_id', identity, sa.ForeignKey('messages.id', ondelete='SET NULL')))
    op.create_index('ix_conversation_members_user_id', 'conversation_members', ['user_id', 'conversation_id'])
    op.create_table('chat_rate_attempts',
        sa.Column('user_id', identity, sa.ForeignKey('usuarios.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('attempts', sa.Integer(), nullable=False),
        sa.Column('expires', sa.Float(), nullable=False))


def downgrade():
    op.drop_table('chat_rate_attempts')
    op.drop_index('ix_conversation_members_user_id', table_name='conversation_members')
    op.drop_table('conversation_members')
    op.drop_index('ix_messages_conversation_id_id', table_name='messages')
    op.drop_table('messages')
    op.drop_table('conversations')
