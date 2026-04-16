"""per-type aliases: rename step_type->type on agent_aliases, rename llm->chat in flow_steps

Revision ID: i9d0e1f2g3h4
Revises: h8c9d0e1f2g3
Create Date: 2026-04-15 22:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


revision: str = 'i9d0e1f2g3h4'
down_revision: Union[str, Sequence[str], None] = 'h8c9d0e1f2g3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(table: str, column: str) -> bool:
    conn = op.get_bind()
    cols = [c["name"] for c in inspect(conn).get_columns(table)]
    return column in cols


def upgrade() -> None:
    conn = op.get_bind()

    # 1. AgentAlias: rename step_type -> type, change unique constraint
    #    The previous migration left us with (name, step_type) unique constraint.
    #    We want (type, name) where type replaces step_type.
    if _column_exists('agent_aliases', 'step_type'):
        with op.batch_alter_table('agent_aliases') as batch_op:
            batch_op.drop_constraint('uq_agent_alias_name_step_type', type_='unique')
            batch_op.alter_column('step_type', new_column_name='type')
            batch_op.create_unique_constraint('uq_agent_alias_type_name', ['type', 'name'])

    # Rename type values: api/llm -> chat
    conn.execute(text("UPDATE agent_aliases SET type = 'chat' WHERE type IN ('llm', 'api')"))
    # Deduplicate after rename (keep lowest id per type+name)
    conn.execute(text("""
        DELETE FROM agent_aliases
        WHERE id NOT IN (
            SELECT MIN(id) FROM agent_aliases GROUP BY type, name
        )
    """))

    # 2. FlowStep: rename step_type llm/api -> chat
    conn.execute(text("UPDATE flow_steps SET step_type = 'chat' WHERE step_type IN ('llm', 'api')"))

    # 3. Drop agent column from flow_steps if it was added
    if _column_exists('flow_steps', 'agent'):
        with op.batch_alter_table('flow_steps') as batch_op:
            batch_op.drop_column('agent')


def downgrade() -> None:
    conn = op.get_bind()

    # Revert step_type chat -> llm in flow_steps
    conn.execute(text("UPDATE flow_steps SET step_type = 'llm' WHERE step_type = 'chat'"))

    # Rename type -> step_type on agent_aliases
    if _column_exists('agent_aliases', 'type'):
        conn.execute(text("UPDATE agent_aliases SET type = 'llm' WHERE type = 'chat'"))
        with op.batch_alter_table('agent_aliases') as batch_op:
            batch_op.drop_constraint('uq_agent_alias_type_name', type_='unique')
            batch_op.alter_column('type', new_column_name='step_type')
            batch_op.create_unique_constraint('uq_agent_alias_name_step_type', ['name', 'step_type'])
