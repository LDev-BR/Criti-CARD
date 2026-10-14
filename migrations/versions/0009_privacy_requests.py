"""Private rights requests, attributable new contacts and retryable file cleanup."""
from alembic import op
import sqlalchemy as sa

revision = '0009_privacy_requests'
down_revision = '0008_user_settings'
branch_labels = None
depends_on = None


def upgrade():
    identity = sa.BigInteger().with_variant(sa.Integer(), 'sqlite')
    # Legacy contacts cannot be safely attributed by matching a mutable email.
    # Keep them unchanged for an operator-reviewed retention decision.
    with op.batch_alter_table('contatos') as batch:
        batch.add_column(sa.Column('user_id', identity, nullable=True))
        batch.create_foreign_key('fk_contatos_user_id', 'usuarios', ['user_id'], ['id'], ondelete='CASCADE')
        batch.create_index('ix_contatos_user_id', ['user_id'])
    op.create_table('privacy_requests',
        sa.Column('id', identity, primary_key=True),
        sa.Column('protocol', sa.String(35), nullable=False),
        sa.Column('user_id', identity, sa.ForeignKey('usuarios.id', ondelete='CASCADE'), nullable=False),
        sa.Column('kind', sa.String(16), nullable=False),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('status', sa.String(16), nullable=False, server_default='received'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('protocol', name='uq_privacy_requests_protocol'),
        sa.CheckConstraint("kind IN ('access','correction','deletion','portability','sharing','consent','objection','other')",
            name='ck_privacy_requests_kind'),
        sa.CheckConstraint("status IN ('received','in_review','answered')", name='ck_privacy_requests_status'),
        sa.CheckConstraint('length(body) BETWEEN 1 AND 3000', name='ck_privacy_requests_body_length'),
        sqlite_autoincrement=True)
    op.create_index('ix_privacy_requests_user_created', 'privacy_requests', ['user_id', 'created_at'])
    op.create_table('privacy_replies',
        sa.Column('id', identity, primary_key=True),
        sa.Column('request_id', identity, sa.ForeignKey('privacy_requests.id', ondelete='CASCADE'), nullable=False),
        sa.Column('responder_id', identity, sa.ForeignKey('usuarios.id', ondelete='SET NULL')),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('received','in_review','answered')", name='ck_privacy_replies_status'),
        sa.CheckConstraint('length(body) BETWEEN 1 AND 3000', name='ck_privacy_replies_body_length'),
        sqlite_autoincrement=True)
    op.create_index('ix_privacy_replies_request_id', 'privacy_replies', ['request_id'])
    op.create_table('pending_image_deletions',
        sa.Column('id', identity, primary_key=True),
        sa.Column('kind', sa.String(8), nullable=False),
        sa.Column('filename', sa.String(255), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('kind', 'filename', name='uq_pending_image_deletions_file'),
        sa.CheckConstraint("kind IN ('avatar','cover')", name='ck_pending_image_deletions_kind'))


def downgrade():
    op.drop_table('pending_image_deletions')
    op.drop_table('privacy_replies')
    op.drop_table('privacy_requests')
    with op.batch_alter_table('contatos') as batch:
        batch.drop_index('ix_contatos_user_id')
        batch.drop_constraint('fk_contatos_user_id', type_='foreignkey')
        batch.drop_column('user_id')
