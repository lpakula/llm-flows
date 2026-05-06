"""add isolated flag to flows and flow_steps

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-06 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0005'
down_revision: Union[str, Sequence[str], None] = '0004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("flows") as batch_op:
        batch_op.add_column(sa.Column('isolated', sa.Boolean(), server_default='0'))

    with op.batch_alter_table("flow_steps") as batch_op:
        batch_op.add_column(sa.Column('isolated', sa.Boolean(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("flow_steps") as batch_op:
        batch_op.drop_column('isolated')
    with op.batch_alter_table("flows") as batch_op:
        batch_op.drop_column('isolated')
