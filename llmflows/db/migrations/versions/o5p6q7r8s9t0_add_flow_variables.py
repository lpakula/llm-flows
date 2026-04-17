"""add flow variables column

Revision ID: o5p6q7r8s9t0
Revises: n4o5p6q7r8s9
Create Date: 2026-04-17 12:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "o5p6q7r8s9t0"
down_revision: Union[str, None] = "n4o5p6q7r8s9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("flows") as batch_op:
        batch_op.add_column(sa.Column("variables", sa.Text(), server_default="{}"))


def downgrade() -> None:
    with op.batch_alter_table("flows") as batch_op:
        batch_op.drop_column("variables")
