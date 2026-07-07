"""add container_id to flow_runs

Revision ID: 0009
Revises: 0008
Create Date: 2026-05-14 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0009'
down_revision: Union[str, Sequence[str], None] = '0008'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("flow_runs")}
    if "container_id" in cols:
        return
    with op.batch_alter_table("flow_runs") as batch_op:
        batch_op.add_column(
            sa.Column('container_id', sa.String(64), nullable=True)
        )


def downgrade() -> None:
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("flow_runs")}
    if "container_id" not in cols:
        return
    with op.batch_alter_table("flow_runs") as batch_op:
        batch_op.drop_column('container_id')
