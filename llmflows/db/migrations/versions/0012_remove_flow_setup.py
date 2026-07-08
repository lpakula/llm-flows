"""remove setup_script and apt_packages from flows

Replaced by per-flow committed Docker images (docker commit after each run).

Revision ID: 0012
Revises: 0011
Create Date: 2026-07-08 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0012'
down_revision: Union[str, Sequence[str], None] = '0011'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("flows")}
    with op.batch_alter_table("flows") as batch_op:
        if "setup_script" in cols:
            batch_op.drop_column('setup_script')
        if "apt_packages" in cols:
            batch_op.drop_column('apt_packages')


def downgrade() -> None:
    with op.batch_alter_table("flows") as batch_op:
        batch_op.add_column(sa.Column('setup_script', sa.Text(), server_default=''))
        batch_op.add_column(sa.Column('apt_packages', sa.Text(), server_default=''))
