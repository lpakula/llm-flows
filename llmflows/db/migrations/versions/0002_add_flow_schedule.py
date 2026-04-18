"""add flow schedule columns

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-18 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0002'
down_revision: Union[str, Sequence[str], None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('flows') as batch_op:
        batch_op.add_column(sa.Column('schedule_cron', sa.String(100), nullable=True))
        batch_op.add_column(sa.Column('schedule_timezone', sa.String(64), nullable=True))
        batch_op.add_column(sa.Column('schedule_next_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('schedule_enabled', sa.Boolean(), server_default='0'))


def downgrade() -> None:
    with op.batch_alter_table('flows') as batch_op:
        batch_op.drop_column('schedule_enabled')
        batch_op.drop_column('schedule_next_at')
        batch_op.drop_column('schedule_timezone')
        batch_op.drop_column('schedule_cron')
