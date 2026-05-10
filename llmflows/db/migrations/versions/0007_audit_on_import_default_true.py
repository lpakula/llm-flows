"""change audit_flows_on_import default to true

Revision ID: 0007
Revises: 0006
Create Date: 2026-05-10 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0007'
down_revision: Union[str, Sequence[str], None] = '0006'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("spaces") as batch_op:
        batch_op.alter_column(
            'audit_flows_on_import',
            server_default='1',
        )


def downgrade() -> None:
    with op.batch_alter_table("spaces") as batch_op:
        batch_op.alter_column(
            'audit_flows_on_import',
            server_default='0',
        )
