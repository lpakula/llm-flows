"""add skills column to flow_steps

Revision ID: g7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-04-15 18:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = 'g7b8c9d0e1f2'
down_revision: Union[str, Sequence[str], None] = 'f6a7b8c9d0e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(table: str, column: str) -> bool:
    conn = op.get_bind()
    cols = [c["name"] for c in inspect(conn).get_columns(table)]
    return column in cols


def upgrade() -> None:
    if not _column_exists('flow_steps', 'skills'):
        with op.batch_alter_table('flow_steps') as batch_op:
            batch_op.add_column(sa.Column('skills', sa.Text, server_default='[]'))


def downgrade() -> None:
    if _column_exists('flow_steps', 'skills'):
        with op.batch_alter_table('flow_steps') as batch_op:
            batch_op.drop_column('skills')
