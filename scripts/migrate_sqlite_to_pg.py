"""One-time migration: copy all data from SQLite to PostgreSQL."""

import os
import sqlite3
import sys

from sqlalchemy import create_engine, text, inspect
from sqlalchemy.orm import sessionmaker


def main():
    sqlite_path = os.environ.get("SQLITE_PATH", "/root/.llmflows/llmflows.db")
    pg_url = os.environ.get("DATABASE_URL")
    if not pg_url:
        print("ERROR: DATABASE_URL not set")
        sys.exit(1)

    print(f"SQLite: {sqlite_path}")
    print(f"Postgres: {pg_url}")

    sqlite_conn = sqlite3.connect(sqlite_path)
    sqlite_conn.row_factory = sqlite3.Row

    pg_engine = create_engine(pg_url)
    Session = sessionmaker(bind=pg_engine)
    pg_session = Session()

    inspector = inspect(pg_engine)
    pg_tables = inspector.get_table_names()

    tables_order = [
        "spaces", "agent_aliases", "agent_configs", "mcp_connectors", "oauth_states",
        "flows", "flow_steps", "flow_versions",
        "flow_runs", "step_runs", "inbox_items",
    ]

    migrated = 0
    for table in tables_order:
        if table not in pg_tables:
            print(f"  SKIP {table} (not in Postgres schema)")
            continue

        pg_count = pg_session.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
        if pg_count > 0:
            print(f"  SKIP {table} (already has {pg_count} rows)")
            continue

        rows = sqlite_conn.execute(f"SELECT * FROM {table}").fetchall()
        if not rows:
            print(f"  SKIP {table} (empty in SQLite)")
            continue

        columns = [desc[0] for desc in sqlite_conn.execute(f"SELECT * FROM {table} LIMIT 1").description]
        pg_columns = [c["name"] for c in inspector.get_columns(table)]
        valid_columns = [c for c in columns if c in pg_columns]

        bool_columns = set()
        for col_info in inspector.get_columns(table):
            if str(col_info["type"]).upper() == "BOOLEAN":
                bool_columns.add(col_info["name"])

        inserted = 0
        skipped = 0
        for row in rows:
            row_dict = {}
            for c in valid_columns:
                val = row[c]
                if c in bool_columns and isinstance(val, int):
                    val = bool(val)
                row_dict[c] = val
            cols = ", ".join(valid_columns)
            placeholders = ", ".join(f":{c}" for c in valid_columns)
            try:
                pg_session.execute(text(f"INSERT INTO {table} ({cols}) VALUES ({placeholders})"), row_dict)
                pg_session.commit()
                inserted += 1
            except Exception:
                skipped += 1
                pg_session.rollback()

        if inserted > 0:
            print(f"  OK {table}: {inserted} rows migrated" + (f" ({skipped} skipped)" if skipped else ""))
            migrated += 1
        elif skipped > 0:
            print(f"  SKIP {table}: all {skipped} rows failed (orphaned FK references)")
        else:
            print(f"  SKIP {table}: no data")

    sqlite_conn.close()
    pg_session.close()
    print(f"\nDone: {migrated} tables migrated to Postgres")


if __name__ == "__main__":
    main()
