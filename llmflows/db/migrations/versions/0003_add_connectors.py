"""add mcp_connectors table, oauth_states table, rename flow_steps.tools to connectors

Revision ID: 0003
Revises: 0002
Create Date: 2026-04-23 00:00:00.000000
"""
import json
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0003'
down_revision: Union[str, Sequence[str], None] = '0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _rewrite_requirements(old_key: str, new_key: str) -> None:
    conn = op.get_bind()
    rows = conn.execute(sa.text("SELECT id, requirements FROM flows WHERE requirements IS NOT NULL AND requirements != ''"))
    for row in rows:
        try:
            data = json.loads(row[1])
        except (json.JSONDecodeError, TypeError):
            continue
        if old_key in data:
            data[new_key] = data.pop(old_key)
            conn.execute(
                sa.text("UPDATE flows SET requirements = :req WHERE id = :id"),
                {"req": json.dumps(data), "id": row[0]},
            )


def upgrade() -> None:
    op.create_table(
        'mcp_connectors',
        sa.Column('id', sa.String(6), primary_key=True),
        sa.Column('server_id', sa.String(50), unique=True, nullable=False),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('command', sa.Text(), server_default=''),
        sa.Column('port', sa.Integer(), nullable=True),
        sa.Column('env', sa.Text(), server_default='{}'),
        sa.Column('credentials', sa.Text(), server_default='{}'),
        sa.Column('enabled', sa.Boolean(), server_default='0'),
        sa.Column('builtin', sa.Boolean(), server_default='0'),
        sa.Column('auth_status', sa.String(30), server_default='not_configured'),
        sa.Column('auth_error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime()),
        sa.Column('updated_at', sa.DateTime()),
    )

    op.create_table(
        'oauth_states',
        sa.Column('state', sa.String(64), primary_key=True),
        sa.Column('connector_id', sa.String(6), nullable=False),
        sa.Column('redirect_uri', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )

    op.alter_column('flow_steps', 'tools', new_column_name='connectors')
    _rewrite_requirements('tools', 'connectors')


def downgrade() -> None:
    _rewrite_requirements('connectors', 'tools')
    op.alter_column('flow_steps', 'connectors', new_column_name='tools')
    op.drop_table('oauth_states')
    op.drop_table('mcp_connectors')
