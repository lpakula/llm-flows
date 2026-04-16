"""add step_type to agent_aliases, tools to flow_steps, rename agent->code

Revision ID: h8c9d0e1f2g3
Revises: g7b8c9d0e1f2
Create Date: 2026-04-15 20:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


revision: str = 'h8c9d0e1f2g3'
down_revision: Union[str, Sequence[str], None] = 'g7b8c9d0e1f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(table: str, column: str) -> bool:
    conn = op.get_bind()
    cols = [c["name"] for c in inspect(conn).get_columns(table)]
    return column in cols


def upgrade() -> None:
    # 1. Add step_type column to agent_aliases
    if not _column_exists('agent_aliases', 'step_type'):
        naming = {"uq": "uq_%(table_name)s_%(column_0_name)s"}
        with op.batch_alter_table('agent_aliases', naming_convention=naming) as batch_op:
            batch_op.add_column(sa.Column('step_type', sa.String(20), server_default='code', nullable=False))
            batch_op.drop_constraint('uq_agent_aliases_name', type_='unique')
            batch_op.create_unique_constraint('uq_agent_alias_name_step_type', ['name', 'step_type'])

    # 2. Add tools column to flow_steps
    if not _column_exists('flow_steps', 'tools'):
        with op.batch_alter_table('flow_steps') as batch_op:
            batch_op.add_column(sa.Column('tools', sa.Text, server_default='[]'))

    # 3. Rename step_type="agent" to "code" in flow_steps
    conn = op.get_bind()
    conn.execute(text("UPDATE flow_steps SET step_type = 'code' WHERE step_type = 'agent'"))

    # 4. Set step_type="code" on existing agent_aliases
    conn.execute(text("UPDATE agent_aliases SET step_type = 'code' WHERE step_type IS NULL OR step_type = ''"))


def downgrade() -> None:
    conn = op.get_bind()

    # Revert step_type="code" back to "agent" in flow_steps
    conn.execute(text("UPDATE flow_steps SET step_type = 'agent' WHERE step_type = 'code'"))

    # Remove tools column from flow_steps
    if _column_exists('flow_steps', 'tools'):
        with op.batch_alter_table('flow_steps') as batch_op:
            batch_op.drop_column('tools')

    # Remove step_type from agent_aliases
    if _column_exists('agent_aliases', 'step_type'):
        with op.batch_alter_table('agent_aliases') as batch_op:
            batch_op.drop_constraint('uq_agent_alias_name_step_type', type_='unique')
            batch_op.create_unique_constraint('uq_agent_alias_name', ['name'])
            batch_op.drop_column('step_type')
