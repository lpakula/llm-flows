"""add prev_gate_failures column to step_runs

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-07 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0005'
down_revision: Union[str, Sequence[str], None] = '0004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("step_runs") as batch_op:
        batch_op.add_column(sa.Column('prev_gate_failures', sa.Text(), server_default='', nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("step_runs") as batch_op:
        batch_op.drop_column('prev_gate_failures')
