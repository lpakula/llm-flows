"""add setup_script and apt_packages to flows

Per-flow dependency isolation: setup_script installs tools into the flow's
tools dir inside the space mount; apt_packages builds a derived runner image.

Revision ID: 0011
Revises: 0010
Create Date: 2026-07-08 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0011'
down_revision: Union[str, Sequence[str], None] = '0010'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("flows")}
    with op.batch_alter_table("flows") as batch_op:
        if "setup_script" not in cols:
            batch_op.add_column(sa.Column('setup_script', sa.Text(), server_default=''))
        if "apt_packages" not in cols:
            batch_op.add_column(sa.Column('apt_packages', sa.Text(), server_default=''))


def downgrade() -> None:
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("flows")}
    with op.batch_alter_table("flows") as batch_op:
        if "setup_script" in cols:
            batch_op.drop_column('setup_script')
        if "apt_packages" in cols:
            batch_op.drop_column('apt_packages')
