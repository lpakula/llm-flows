"""remove code agents and migrate legacy code step types

Revision ID: 0010
Revises: 0009
Create Date: 2026-07-07 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op


revision: str = '0010'
down_revision: Union[str, Sequence[str], None] = '0009'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("UPDATE flow_steps SET step_type = 'agent' WHERE step_type = 'code'")
    op.execute("DELETE FROM agent_aliases WHERE type = 'code'")


def downgrade() -> None:
    pass
