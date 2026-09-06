"""fine_tunes table for domain Marlin fine-tune jobs

Revision ID: 006_fine_tunes
Revises: 005_tasks
Create Date: 2026-09-06
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "006_fine_tunes"
down_revision: Union[str, Sequence[str], None] = "005_tasks"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    fine_tune_status = postgresql.ENUM(
        "QUEUED",
        "PROCESSING",
        "COMPLETED",
        "FAILED",
        name="fine_tune_status",
        create_type=False,
    )
    fine_tune_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "fine_tunes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.String(32), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("status", fine_tune_status, nullable=False),
        sa.Column("error_msg", sa.Text(), nullable=True),
        sa.Column("s3_prefix", sa.String(512), nullable=False),
        sa.Column("task_ids", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("manifest", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("user_id", "name", name="uq_fine_tunes_user_name"),
    )
    op.create_index("ix_fine_tunes_user_id", "fine_tunes", ["user_id"])
    op.create_index("ix_fine_tunes_project_id", "fine_tunes", ["project_id"])


def downgrade() -> None:
    op.drop_index("ix_fine_tunes_project_id", table_name="fine_tunes")
    op.drop_index("ix_fine_tunes_user_id", table_name="fine_tunes")
    op.drop_table("fine_tunes")
    op.execute("DROP TYPE IF EXISTS fine_tune_status")
