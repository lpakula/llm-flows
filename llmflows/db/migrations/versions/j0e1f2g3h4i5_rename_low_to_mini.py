"""rename alias tier low -> mini

Revision ID: j0e1f2g3h4i5
Revises: i9d0e1f2g3h4
Create Date: 2026-04-16 10:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text


revision: str = "j0e1f2g3h4i5"
down_revision: Union[str, None] = "i9d0e1f2g3h4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(text("UPDATE agent_aliases SET name = 'mini' WHERE name = 'low'"))


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(text("UPDATE agent_aliases SET name = 'low' WHERE name = 'mini'"))
