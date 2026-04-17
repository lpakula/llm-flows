"""add flow starred column

Revision ID: q7r8s9t0u1v2
Revises: p6q7r8s9t0u1
Create Date: 2026-04-17 15:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "q7r8s9t0u1v2"
down_revision: Union[str, None] = "p6q7r8s9t0u1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("flows") as batch_op:
        batch_op.add_column(sa.Column("starred", sa.Boolean(), server_default="0"))


def downgrade() -> None:
    with op.batch_alter_table("flows") as batch_op:
        batch_op.drop_column("starred")
