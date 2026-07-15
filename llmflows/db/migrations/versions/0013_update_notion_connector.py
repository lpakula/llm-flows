"""update notion connector to official @notionhq/notion-mcp-server package

Revision ID: 0013
Revises: 0012
Create Date: 2026-07-15 00:00:00.000000
"""
import json
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: Union[str, Sequence[str], None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_OLD_COMMAND = "npx @modelcontextprotocol/server-notion"
_NEW_COMMAND = "npx @notionhq/notion-mcp-server"


def _migrate_credentials(creds: dict) -> dict:
    if "NOTION_API_KEY" in creds and "NOTION_TOKEN" not in creds:
        creds["NOTION_TOKEN"] = creds.pop("NOTION_API_KEY")
    else:
        creds.pop("NOTION_API_KEY", None)
    return creds


def upgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text("SELECT id, command, credentials FROM mcp_connectors WHERE server_id = 'notion'")
    ).fetchall()
    for row in rows:
        creds = _migrate_credentials(json.loads(row.credentials or "{}"))
        command = row.command or ""
        if command == _OLD_COMMAND or "@modelcontextprotocol/server-notion" in command:
            command = _NEW_COMMAND
        bind.execute(
            sa.text(
                "UPDATE mcp_connectors SET command = :command, credentials = :credentials "
                "WHERE id = :id"
            ),
            {"command": command, "credentials": json.dumps(creds), "id": row.id},
        )


def downgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text("SELECT id, command, credentials FROM mcp_connectors WHERE server_id = 'notion'")
    ).fetchall()
    for row in rows:
        creds = json.loads(row.credentials or "{}")
        if "NOTION_TOKEN" in creds and "NOTION_API_KEY" not in creds:
            creds["NOTION_API_KEY"] = creds.pop("NOTION_TOKEN")
        else:
            creds.pop("NOTION_TOKEN", None)
        command = row.command or ""
        if command == _NEW_COMMAND or "@notionhq/notion-mcp-server" in command:
            command = _OLD_COMMAND
        bind.execute(
            sa.text(
                "UPDATE mcp_connectors SET command = :command, credentials = :credentials "
                "WHERE id = :id"
            ),
            {"command": command, "credentials": json.dumps(creds), "id": row.id},
        )
