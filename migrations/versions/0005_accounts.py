"""Recovery links, email verification and account state snapshots."""
from alembic import op
import sqlalchemy as sa

revision = "0005_accounts"
down_revision = "0001_core"
branch_labels = ("accounts",)
depends_on = None


def upgrade():
    identity = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
    op.add_column("usuarios", sa.Column("email_verified", sa.Integer(), server_default="0", nullable=False))
    op.create_table(
        "account_tokens",
        sa.Column("id", identity, primary_key=True),
        sa.Column("user_id", identity, sa.ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("purpose", sa.String(8), nullable=False),
        sa.Column("email_snapshot", sa.Text(), nullable=False),
        sa.Column("session_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("token_hash", name="uq_account_token_hash"),
        sa.CheckConstraint("purpose IN ('reset','verify')", name="ck_account_token_purpose"),
    )
    op.create_index("ix_account_token_user_purpose", "account_tokens", ["user_id", "purpose"])
    op.create_index("ix_account_token_expiry", "account_tokens", ["expires_at"])


def downgrade():
    op.drop_table("account_tokens")
    with op.batch_alter_table("usuarios") as batch:
        batch.drop_column("email_verified")
