"""Merge the independent MVP domains into one deployable revision."""

revision = '0006_merge'
down_revision = ('0002_backlog', '0003_social', '0004_chat', '0005_accounts')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
