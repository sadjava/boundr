"""per-pipeline inference cache

Revision ID: 003_inferences
Revises: 002_project_catalogs
Create Date: 2026-09-03
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "003_inferences"
down_revision: Union[str, Sequence[str], None] = "002_project_catalogs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column("pipeline", sa.String(32), nullable=False, server_default="overlap"),
    )
    op.create_table(
        "inferences",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("video_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("pipeline", sa.String(32), nullable=False),
        sa.Column("s3_key", sa.String(512), nullable=True),
        sa.Column("data", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["video_id"], ["videos.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("video_id", "pipeline", name="uq_inferences_video_pipeline"),
    )
    op.create_index("ix_inferences_video_id", "inferences", ["video_id"])


def downgrade() -> None:
    op.drop_index("ix_inferences_video_id", table_name="inferences")
    op.drop_table("inferences")
    op.drop_column("jobs", "pipeline")
