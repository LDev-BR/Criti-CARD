"""Private personal collections, independent from reviews."""
from alembic import op
import sqlalchemy as sa

revision = "0002_backlog"
down_revision = "0001_core"
branch_labels = ("backlog",)
depends_on = None


def upgrade():
    identity = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
    op.create_table(
        "backlog_items",
        sa.Column("id", identity, primary_key=True),
        sa.Column("user_id", identity, sa.ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False),
        sa.Column("work_id", identity, sa.ForeignKey("obras.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(20), server_default="planned", nullable=False),
        sa.Column("visibility", sa.String(10), server_default="private", nullable=False),
        sa.Column("progress", sa.Integer()),
        sa.Column("progress_unit", sa.String(12)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", "work_id", name="uq_backlog_user_work"),
        sa.CheckConstraint("status IN ('planned','in_progress','completed','paused','dropped')", name="ck_backlog_status"),
        sa.CheckConstraint("visibility IN ('private','public')", name="ck_backlog_visibility"),
        sa.CheckConstraint("progress IS NULL OR (progress >= 0 AND progress <= 100000)", name="ck_backlog_progress"),
        sa.CheckConstraint("progress_unit IS NULL OR progress_unit IN ('hours','episodes','chapters')", name="ck_backlog_progress_unit"),
    )
    op.create_index("ix_backlog_user_status", "backlog_items", ["user_id", "status"])
    op.create_index("ix_backlog_user_visibility", "backlog_items", ["user_id", "visibility"])
    op.create_index("ix_backlog_work", "backlog_items", ["work_id"])


def downgrade():
    op.drop_table("backlog_items")
