"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-04-17 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0001'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'agent_aliases',
        sa.Column('id', sa.String(6), primary_key=True),
        sa.Column('name', sa.String(50), nullable=False),
        sa.Column('type', sa.String(20), nullable=False, server_default='code'),
        sa.Column('agent', sa.String(50), nullable=False, server_default='cursor'),
        sa.Column('model', sa.String(100), nullable=False),
        sa.Column('position', sa.Integer(), default=0),
        sa.Column('created_at', sa.DateTime()),
        sa.Column('updated_at', sa.DateTime()),
        sa.UniqueConstraint('type', 'name', name='uq_agent_alias_type_name'),
    )

    op.create_table(
        'agent_configs',
        sa.Column('id', sa.String(6), primary_key=True),
        sa.Column('agent', sa.String(50), nullable=False),
        sa.Column('key', sa.String(255), nullable=False),
        sa.Column('value', sa.Text(), server_default=''),
        sa.UniqueConstraint('agent', 'key', name='uq_agent_config_key'),
    )

    op.create_table(
        'spaces',
        sa.Column('id', sa.String(6), primary_key=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('path', sa.Text(), nullable=False, unique=True),
        sa.Column('is_git_repo', sa.Boolean(), server_default='1'),
        sa.Column('max_concurrent_tasks', sa.Integer(), server_default='1'),
        sa.Column('inbox_completed_runs', sa.Boolean(), server_default='1'),
        sa.Column('variables', sa.Text(), server_default='{}'),
        sa.Column('created_at', sa.DateTime()),
    )

    op.create_table(
        'flows',
        sa.Column('id', sa.String(6), primary_key=True),
        sa.Column('space_id', sa.String(6), sa.ForeignKey('spaces.id'), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), server_default=''),
        sa.Column('requirements', sa.Text(), server_default='{}'),
        sa.Column('variables', sa.Text(), server_default='{}'),
        sa.Column('max_concurrent_runs', sa.Integer(), server_default='1'),
        sa.Column('max_spend_usd', sa.Float(), nullable=True),
        sa.Column('starred', sa.Boolean(), server_default='0'),
        sa.Column('created_at', sa.DateTime()),
        sa.Column('updated_at', sa.DateTime()),
        sa.UniqueConstraint('space_id', 'name', name='uq_flow_space_name'),
    )

    op.create_table(
        'flow_steps',
        sa.Column('id', sa.String(6), primary_key=True),
        sa.Column('flow_id', sa.String(6), sa.ForeignKey('flows.id'), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('content', sa.Text(), server_default=''),
        sa.Column('gates', sa.Text(), server_default='[]'),
        sa.Column('ifs', sa.Text(), server_default='[]'),
        sa.Column('agent_alias', sa.String(50), server_default='normal'),
        sa.Column('step_type', sa.String(20), server_default='agent'),
        sa.Column('allow_max', sa.Boolean(), server_default='0'),
        sa.Column('max_gate_retries', sa.Integer(), server_default='5'),
        sa.Column('skills', sa.Text(), server_default='[]'),
        sa.Column('tools', sa.Text(), server_default='[]'),
        sa.Column('created_at', sa.DateTime()),
        sa.Column('updated_at', sa.DateTime()),
    )

    op.create_table(
        'flow_runs',
        sa.Column('id', sa.String(6), primary_key=True),
        sa.Column('space_id', sa.String(6), sa.ForeignKey('spaces.id'), nullable=False),
        sa.Column('flow_id', sa.String(6), sa.ForeignKey('flows.id'), nullable=True),
        sa.Column('flow_snapshot', sa.Text(), nullable=True),
        sa.Column('current_step', sa.String(255), server_default=''),
        sa.Column('outcome', sa.String(50), nullable=True),
        sa.Column('log_path', sa.Text(), server_default=''),
        sa.Column('prompt', sa.Text(), server_default=''),
        sa.Column('summary', sa.Text(), server_default=''),
        sa.Column('steps_completed', sa.Text(), server_default='[]'),
        sa.Column('recovery_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('one_shot', sa.Boolean(), server_default='0'),
        sa.Column('paused_at', sa.DateTime(), nullable=True),
        sa.Column('resume_prompt', sa.Text(), server_default=''),
        sa.Column('created_at', sa.DateTime()),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
    )

    op.create_table(
        'step_runs',
        sa.Column('id', sa.String(6), primary_key=True),
        sa.Column('flow_run_id', sa.String(6), sa.ForeignKey('flow_runs.id'), nullable=False),
        sa.Column('step_name', sa.String(255), nullable=False),
        sa.Column('step_position', sa.Integer(), nullable=False),
        sa.Column('flow_name', sa.String(255), nullable=False),
        sa.Column('agent', sa.String(50), nullable=False, server_default='cursor'),
        sa.Column('model', sa.String(100), nullable=False, server_default=''),
        sa.Column('log_path', sa.Text(), server_default=''),
        sa.Column('prompt', sa.Text(), server_default=''),
        sa.Column('outcome', sa.String(50), nullable=True),
        sa.Column('attempt', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('gate_failures', sa.Text(), server_default=''),
        sa.Column('user_response', sa.Text(), server_default=''),
        sa.Column('cost_usd', sa.Float(), nullable=True),
        sa.Column('token_count', sa.Integer(), nullable=True),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('awaiting_user_at', sa.DateTime(), nullable=True),
    )

    op.create_table(
        'inbox_items',
        sa.Column('id', sa.String(6), primary_key=True),
        sa.Column('type', sa.String(32), nullable=False),
        sa.Column('reference_id', sa.String(6), nullable=False),
        sa.Column('space_id', sa.String(6), sa.ForeignKey('spaces.id'), nullable=False),
        sa.Column('title', sa.Text(), server_default=''),
        sa.Column('created_at', sa.DateTime()),
        sa.Column('archived_at', sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table('inbox_items')
    op.drop_table('step_runs')
    op.drop_table('flow_runs')
    op.drop_table('flow_steps')
    op.drop_table('flows')
    op.drop_table('spaces')
    op.drop_table('agent_configs')
    op.drop_table('agent_aliases')
