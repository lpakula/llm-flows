"""add inbox_items table

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-04-10 12:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, Sequence[str], None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'inbox_items',
        sa.Column('id', sa.String(6), primary_key=True),
        sa.Column('type', sa.String(32), nullable=False),
        sa.Column('reference_id', sa.String(6), nullable=False),
        sa.Column('task_id', sa.String(6), sa.ForeignKey('tasks.id'), nullable=False),
        sa.Column('project_id', sa.String(6), sa.ForeignKey('projects.id'), nullable=False),
        sa.Column('title', sa.Text(), server_default=''),
        sa.Column('created_at', sa.DateTime()),
        sa.Column('archived_at', sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table('inbox_items')
