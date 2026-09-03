"""inference model version column

Revision ID: 004_inference_version
Revises: 003_inferences
Create Date: 2026-09-03
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "004_inference_version"
down_revision: Union[str, Sequence[str], None] = "003_inferences"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "inferences",
        sa.Column("model_version", sa.Integer(), nullable=False, server_default="1"),
    )


def downgrade() -> None:
    op.drop_column("inferences", "model_version")
