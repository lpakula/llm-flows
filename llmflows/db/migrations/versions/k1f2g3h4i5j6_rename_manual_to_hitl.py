"""rename step_type manual -> hitl, alias type chat -> pi

Revision ID: k1f2g3h4i5j6
Revises: j0e1f2g3h4i5
Create Date: 2026-04-16 12:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text


revision: str = "k1f2g3h4i5j6"
down_revision: Union[str, None] = "j0e1f2g3h4i5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(text("UPDATE flow_steps SET step_type = 'hitl' WHERE step_type = 'manual'"))
    conn.execute(text("UPDATE flow_steps SET step_type = 'default' WHERE step_type = 'chat'"))
    conn.execute(text(
        "UPDATE agent_aliases SET model = agent || '/' || model, agent = 'pi', type = 'pi' "
        "WHERE type = 'chat'"
    ))


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(text("UPDATE flow_steps SET step_type = 'manual' WHERE step_type = 'hitl'"))
    conn.execute(text("UPDATE flow_steps SET step_type = 'chat' WHERE step_type = 'default'"))
    conn.execute(text(
        "UPDATE agent_aliases SET agent = substr(model, 1, instr(model, '/') - 1), "
        "model = substr(model, instr(model, '/') + 1), type = 'chat' "
        "WHERE type = 'pi'"
    ))
