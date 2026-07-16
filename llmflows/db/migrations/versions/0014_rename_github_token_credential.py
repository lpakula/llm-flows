"""rename github connector credential to GITHUB_PERSONAL_ACCESS_TOKEN

Revision ID: 0014
Revises: 0013
Create Date: 2026-07-15 00:00:00.000000
"""
import json
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: Union[str, Sequence[str], None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_OLD_KEY = "GITHUB_TOKEN"
_NEW_KEY = "GITHUB_PERSONAL_ACCESS_TOKEN"


def _rename_key(creds: dict, *, old: str, new: str) -> dict:
    if old in creds and new not in creds:
        creds[new] = creds.pop(old)
    else:
        creds.pop(old, None)
    return creds


def upgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text("SELECT id, credentials FROM mcp_connectors WHERE server_id = 'github'")
    ).fetchall()
    for row in rows:
        creds = _rename_key(json.loads(row.credentials or "{}"), old=_OLD_KEY, new=_NEW_KEY)
        bind.execute(
            sa.text(
                "UPDATE mcp_connectors SET credentials = :credentials WHERE id = :id"
            ),
            {"credentials": json.dumps(creds), "id": row.id},
        )


def downgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text("SELECT id, credentials FROM mcp_connectors WHERE server_id = 'github'")
    ).fetchall()
    for row in rows:
        creds = _rename_key(json.loads(row.credentials or "{}"), old=_NEW_KEY, new=_OLD_KEY)
        bind.execute(
            sa.text(
                "UPDATE mcp_connectors SET credentials = :credentials WHERE id = :id"
            ),
            {"credentials": json.dumps(creds), "id": row.id},
        )
