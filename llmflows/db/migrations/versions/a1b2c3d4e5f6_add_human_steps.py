"""add human steps

Revision ID: a1b2c3d4e5f6
Revises: 999b2b4c587a
Create Date: 2026-04-10 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '999b2b4c587a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('flow_steps') as batch_op:
        batch_op.add_column(sa.Column('step_type', sa.String(length=20), nullable=True, server_default='agent'))

    with op.batch_alter_table('step_runs') as batch_op:
        batch_op.add_column(sa.Column('user_response', sa.Text(), nullable=True, server_default=''))
        batch_op.add_column(sa.Column('awaiting_user_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('step_runs') as batch_op:
        batch_op.drop_column('awaiting_user_at')
        batch_op.drop_column('user_response')

    with op.batch_alter_table('flow_steps') as batch_op:
        batch_op.drop_column('step_type')
