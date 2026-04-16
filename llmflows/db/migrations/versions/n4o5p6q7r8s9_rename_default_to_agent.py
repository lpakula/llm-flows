"""rename step_type default -> agent

Revision ID: n4o5p6q7r8s9
Revises: m3n4o5p6q7r8
Create Date: 2026-04-16 22:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text


revision: str = "n4o5p6q7r8s9"
down_revision: Union[str, None] = "m3n4o5p6q7r8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(text("UPDATE flow_steps SET step_type = 'agent' WHERE step_type = 'default'"))


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(text("UPDATE flow_steps SET step_type = 'default' WHERE step_type = 'agent'"))
