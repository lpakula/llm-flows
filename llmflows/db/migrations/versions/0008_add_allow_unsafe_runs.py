"""add block_unsafe_runs to spaces

Revision ID: 0008
Revises: 0007
Create Date: 2026-05-10 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0008'
down_revision: Union[str, Sequence[str], None] = '0007'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("spaces") as batch_op:
        batch_op.add_column(
            sa.Column('block_unsafe_runs', sa.Boolean(), server_default='1', nullable=False)
        )


def downgrade() -> None:
    with op.batch_alter_table("spaces") as batch_op:
        batch_op.drop_column('block_unsafe_runs')
