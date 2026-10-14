"""Add explicit group-chat identity and membership workflows."""
from alembic import op
import sqlalchemy as sa

revision = '0014_group_chats'
down_revision = '0013_progression_social_access'
branch_labels = None
depends_on = None


def upgrade():
    identifier = sa.BigInteger().with_variant(sa.Integer(), 'sqlite')
    op.add_column('conversations', sa.Column('kind', sa.String(16), nullable=False, server_default='direct'))
    op.add_column('conversation_members', sa.Column('role', sa.String(16), nullable=False, server_default='member'))
    op.add_column('conversation_members', sa.Column('joined_at', sa.DateTime(timezone=True), nullable=True))
    with op.batch_alter_table('messages') as batch:
        batch.add_column(sa.Column('redacted_at', sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column('redacted_by', identifier,
            sa.ForeignKey('usuarios.id', name='fk_messages_redacted_by_usuarios',
                ondelete='SET NULL'), nullable=True))

    op.create_table('group_chats',
        sa.Column('conversation_id', identifier, sa.ForeignKey('conversations.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('owner_id', identifier, sa.ForeignKey('usuarios.id', ondelete='SET NULL')),
        sa.Column('creator_id', identifier, sa.ForeignKey('usuarios.id', ondelete='SET NULL')),
        sa.Column('name', sa.String(60), nullable=False), sa.Column('slug', sa.String(80), nullable=False),
        sa.Column('description', sa.String(500), nullable=False, server_default=''),
        sa.Column('mode', sa.String(16), nullable=False),
        sa.Column('minimum_level', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('visual_token', sa.String(24), nullable=False, server_default='gold'),
        sa.Column('archived', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('slug', name='uq_group_chats_slug'),
        sa.CheckConstraint("mode IN ('open','closed')", name='ck_group_chats_mode'),
        sa.CheckConstraint('minimum_level >= 1', name='ck_group_chats_minimum_level'),
        sa.CheckConstraint('archived IN (0,1)', name='ck_group_chats_archived'))
    op.create_index('ix_group_chats_discovery','group_chats',['archived','created_at'])
    op.create_table('group_join_requests',
        sa.Column('id', identifier, primary_key=True),
        sa.Column('conversation_id', identifier, sa.ForeignKey('conversations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', identifier, sa.ForeignKey('usuarios.id', ondelete='CASCADE'), nullable=False),
        sa.Column('status', sa.String(16), nullable=False, server_default='pending'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('resolved_at', sa.DateTime(timezone=True)),
        sa.Column('resolved_by', identifier, sa.ForeignKey('usuarios.id', ondelete='SET NULL')),
        sa.CheckConstraint("status IN ('pending','approved','denied','cancelled')", name='ck_group_join_requests_status'),
        sqlite_autoincrement=True)
    op.create_index('uq_group_join_requests_pending', 'group_join_requests', ['conversation_id','user_id'],
        unique=True, sqlite_where=sa.text("status = 'pending'"), postgresql_where=sa.text("status = 'pending'"))
    op.create_index('ix_group_join_requests_group_status', 'group_join_requests',
        ['conversation_id','status','created_at'])
    op.create_table('group_invites',
        sa.Column('id', identifier, primary_key=True),
        sa.Column('conversation_id', identifier, sa.ForeignKey('conversations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('inviter_id', identifier, sa.ForeignKey('usuarios.id', ondelete='CASCADE'), nullable=False),
        sa.Column('invitee_id', identifier, sa.ForeignKey('usuarios.id', ondelete='CASCADE'), nullable=False),
        sa.Column('status', sa.String(16), nullable=False, server_default='pending'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('resolved_at', sa.DateTime(timezone=True)),
        sa.CheckConstraint("status IN ('pending','accepted','declined','cancelled')", name='ck_group_invites_status'),
        sqlite_autoincrement=True)
    op.create_index('uq_group_invites_pending', 'group_invites', ['conversation_id','invitee_id'],
        unique=True, sqlite_where=sa.text("status = 'pending'"), postgresql_where=sa.text("status = 'pending'"))
    op.create_index('ix_group_invites_invitee_status', 'group_invites', ['invitee_id','status','created_at'])

    with op.batch_alter_table('reports') as batch:
        batch.drop_constraint('ck_reports_target_type', type_='check')
        batch.create_check_constraint('ck_reports_target_type', "target_type IN ('card','comment','user','chat_message')")


def downgrade():
    with op.batch_alter_table('reports') as batch:
        batch.drop_constraint('ck_reports_target_type', type_='check')
        batch.create_check_constraint('ck_reports_target_type', "target_type IN ('card','comment','user')")
    op.drop_table('group_invites')
    op.drop_table('group_join_requests')
    op.drop_table('group_chats')
    with op.batch_alter_table('messages') as batch:
        batch.drop_column('redacted_by')
        batch.drop_column('redacted_at')
    op.drop_column('conversation_members','joined_at')
    op.drop_column('conversation_members','role')
    op.drop_column('conversations','kind')
