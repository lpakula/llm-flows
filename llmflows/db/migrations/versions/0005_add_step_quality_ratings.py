"""add step_quality_ratings table

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
    op.create_table(
        'step_quality_ratings',
        sa.Column('id', sa.String(6), primary_key=True),
        sa.Column('step_run_id', sa.String(6), sa.ForeignKey('step_runs.id'), nullable=False),
        sa.Column('flow_id', sa.String(6), sa.ForeignKey('flows.id'), nullable=False),
        sa.Column('step_name', sa.String(255), nullable=False),
        sa.Column('model', sa.String(100), nullable=False, server_default=''),
        sa.Column('agent_alias', sa.String(50), nullable=False, server_default=''),
        sa.Column('rating', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime()),
        sa.UniqueConstraint('step_run_id', name='uq_rating_step_run'),
    )


def downgrade() -> None:
    op.drop_table('step_quality_ratings')
