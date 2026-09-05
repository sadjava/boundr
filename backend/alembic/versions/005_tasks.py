"""project -> task -> video

Revision ID: 005_tasks
Revises: 004_inference_version
Create Date: 2026-09-05
"""

import uuid
from datetime import datetime, timezone
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "005_tasks"
down_revision: Union[str, Sequence[str], None] = "004_inference_version"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tasks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_tasks_project_id", "tasks", ["project_id"])

    op.add_column("videos", sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=True))

    conn = op.get_bind()
    rows = conn.execute(sa.text("SELECT DISTINCT project_id FROM videos")).fetchall()
    now = datetime.now(timezone.utc)
    for (project_id,) in rows:
        task_id = uuid.uuid4()
        conn.execute(
            sa.text(
                "INSERT INTO tasks (id, project_id, name, created_at, updated_at) "
                "VALUES (:id, :project_id, :name, :ts, :ts)"
            ),
            {"id": task_id, "project_id": project_id, "name": "Default", "ts": now},
        )
        conn.execute(
            sa.text("UPDATE videos SET task_id = :tid WHERE project_id = :pid AND task_id IS NULL"),
            {"tid": task_id, "pid": project_id},
        )

    op.alter_column("videos", "task_id", nullable=False)
    op.create_foreign_key(
        "fk_videos_task_id",
        "videos",
        "tasks",
        ["task_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_videos_task_id", "videos", ["task_id"])


def downgrade() -> None:
    op.drop_index("ix_videos_task_id", table_name="videos")
    op.drop_constraint("fk_videos_task_id", "videos", type_="foreignkey")
    op.drop_column("videos", "task_id")
    op.drop_index("ix_tasks_project_id", table_name="tasks")
    op.drop_table("tasks")
