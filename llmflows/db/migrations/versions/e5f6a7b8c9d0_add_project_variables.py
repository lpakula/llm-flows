"""add variables column to spaces

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-04-10 18:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e5f6a7b8c9d0'
down_revision: Union[str, Sequence[str], None] = 'd4e5f6a7b8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('spaces') as batch_op:
        batch_op.add_column(sa.Column('variables', sa.Text(), nullable=True, server_default='{}'))


def downgrade() -> None:
    with op.batch_alter_table('spaces') as batch_op:
        batch_op.drop_column('variables')
