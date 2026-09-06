"""fine_tunes.hidden for picker visibility

Revision ID: 007_fine_tune_hidden
Revises: 006_fine_tunes
Create Date: 2026-09-06
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "007_fine_tune_hidden"
down_revision: Union[str, Sequence[str], None] = "006_fine_tunes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "fine_tunes",
        sa.Column("hidden", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )


def downgrade() -> None:
    op.drop_column("fine_tunes", "hidden")
