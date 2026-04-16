"""remove tasks, rename task_runs to flow_runs

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-04-15 12:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = 'f6a7b8c9d0e1'
down_revision: Union[str, Sequence[str], None] = 'e5f6a7b8c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(name: str) -> bool:
    conn = op.get_bind()
    return name in inspect(conn).get_table_names()


def _column_exists(table: str, column: str) -> bool:
    conn = op.get_bind()
    cols = [c["name"] for c in inspect(conn).get_columns(table)]
    return column in cols


def upgrade() -> None:
    # --- task_runs -> flow_runs ---
    if _table_exists('task_runs'):
        op.rename_table('task_runs', 'flow_runs')

    if _table_exists('flow_runs'):
        if not _column_exists('flow_runs', 'flow_id'):
            with op.batch_alter_table('flow_runs') as batch_op:
                batch_op.add_column(sa.Column('flow_id', sa.String(6), nullable=True))

        for col in ('task_id', 'flow_name', 'user_prompt'):
            if _column_exists('flow_runs', col):
                with op.batch_alter_table('flow_runs') as batch_op:
                    batch_op.drop_column(col)

    # --- step_runs: run_id -> flow_run_id ---
    if _table_exists('step_runs') and _column_exists('step_runs', 'run_id'):
        with op.batch_alter_table('step_runs') as batch_op:
            batch_op.alter_column('run_id', new_column_name='flow_run_id')

    # --- inbox_items: drop task_id ---
    if _table_exists('inbox_items') and _column_exists('inbox_items', 'task_id'):
        with op.batch_alter_table('inbox_items') as batch_op:
            batch_op.drop_column('task_id')

    # --- drop tasks table ---
    if _table_exists('tasks'):
        op.drop_table('tasks')


def downgrade() -> None:
    # Recreate tasks table
    if not _table_exists('tasks'):
        op.create_table(
            'tasks',
            sa.Column('id', sa.String(6), primary_key=True),
            sa.Column('space_id', sa.String(6), sa.ForeignKey('spaces.id'), nullable=False),
            sa.Column('name', sa.String(255), server_default=''),
            sa.Column('description', sa.Text, server_default=''),
            sa.Column('type', sa.String(20), server_default='feature'),
            sa.Column('default_flow_name', sa.String(255), nullable=True),
            sa.Column('task_status', sa.String(50), server_default='backlog'),
            sa.Column('worktree_branch', sa.String(255), server_default=''),
            sa.Column('created_at', sa.DateTime),
        )

    # Add task_id back to inbox_items
    if _table_exists('inbox_items') and not _column_exists('inbox_items', 'task_id'):
        with op.batch_alter_table('inbox_items') as batch_op:
            batch_op.add_column(sa.Column('task_id', sa.String(6), nullable=True))

    # Rename flow_run_id -> run_id in step_runs
    if _table_exists('step_runs') and _column_exists('step_runs', 'flow_run_id'):
        with op.batch_alter_table('step_runs') as batch_op:
            batch_op.alter_column('flow_run_id', new_column_name='run_id')

    # Add back columns to flow_runs and rename to task_runs
    if _table_exists('flow_runs'):
        with op.batch_alter_table('flow_runs') as batch_op:
            if not _column_exists('flow_runs', 'task_id'):
                batch_op.add_column(sa.Column('task_id', sa.String(6), nullable=True))
            if not _column_exists('flow_runs', 'flow_name'):
                batch_op.add_column(sa.Column('flow_name', sa.String(255), nullable=True))
            if not _column_exists('flow_runs', 'user_prompt'):
                batch_op.add_column(sa.Column('user_prompt', sa.Text, server_default=''))
            if _column_exists('flow_runs', 'flow_id'):
                batch_op.drop_column('flow_id')

        op.rename_table('flow_runs', 'task_runs')
