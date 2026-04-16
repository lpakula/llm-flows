"""add cost_usd and token_count to step_runs

Revision ID: l2m3n4o5p6q7
Revises: k1f2g3h4i5j6
Create Date: 2026-04-16 14:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "l2m3n4o5p6q7"
down_revision: Union[str, None] = "k1f2g3h4i5j6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("step_runs") as batch_op:
        batch_op.add_column(sa.Column("cost_usd", sa.Float, nullable=True))
        batch_op.add_column(sa.Column("token_count", sa.Integer, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("step_runs") as batch_op:
        batch_op.drop_column("token_count")
        batch_op.drop_column("cost_usd")
