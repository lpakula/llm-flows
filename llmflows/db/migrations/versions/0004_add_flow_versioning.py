"""add flow_versions table and version column to flows

Revision ID: 0004
Revises: 0003
Create Date: 2026-04-30 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0004'
down_revision: Union[str, Sequence[str], None] = '0003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'flow_versions',
        sa.Column('id', sa.String(6), primary_key=True),
        sa.Column('flow_id', sa.String(6), sa.ForeignKey('flows.id'), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('snapshot', sa.Text(), nullable=False),
        sa.Column('description', sa.Text(), server_default=''),
        sa.Column('created_at', sa.DateTime()),
    )

    with op.batch_alter_table("flows") as batch_op:
        batch_op.add_column(sa.Column('version', sa.Integer(), nullable=True, server_default='1'))


def downgrade() -> None:
    with op.batch_alter_table("flows") as batch_op:
        batch_op.drop_column('version')
    op.drop_table('flow_versions')
