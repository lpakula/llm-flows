"""remove maestro connector from catalog installs

Revision ID: 0015
Revises: 0014
Create Date: 2026-07-15 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: Union[str, Sequence[str], None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("DELETE FROM mcp_connectors WHERE server_id = 'maestro'"))


def downgrade() -> None:
    # Maestro was removed from the catalog; do not re-insert.
    pass
