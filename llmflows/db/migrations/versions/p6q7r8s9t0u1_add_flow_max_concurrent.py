"""add flow max_concurrent_runs column

Revision ID: p6q7r8s9t0u1
Revises: o5p6q7r8s9t0
Create Date: 2026-04-17 14:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "p6q7r8s9t0u1"
down_revision: Union[str, None] = "o5p6q7r8s9t0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("flows") as batch_op:
        batch_op.add_column(sa.Column("max_concurrent_runs", sa.Integer(), server_default="1"))


def downgrade() -> None:
    with op.batch_alter_table("flows") as batch_op:
        batch_op.drop_column("max_concurrent_runs")
