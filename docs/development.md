# Development

## Prerequisites

- Python 3.11+
- Node.js 18+ (for the frontend and browser tools)
- [uv](https://docs.astral.sh/uv/) (recommended) or pip
- Docker (for running tests)

## Setup

```bash
git clone https://github.com/lpakula/llm-flows.git
cd llm-flows

# Install in dev mode
uv tool install -e .

# Install frontend dependencies
cd llmflows/ui/frontend
npm install


# Verify
llmflows --version
```

Changes to Python files are reflected immediately — no reinstall needed.

## Running the UI in dev mode

Dev mode runs Vite with HMR for the frontend and FastAPI with auto-reload for the backend:

```bash
llmflows ui --dev
```

This starts two servers: a Vite dev server (for the React frontend) and a FastAPI backend. Open the Vite URL shown in the terminal.

## Running Tests

Tests run in Docker to ensure a consistent environment:

```bash
# Run all tests
./scripts/test.sh

# Run a specific test file
./scripts/test.sh tests/test_api.py

# Run a specific test
./scripts/test.sh tests/test_api.py::test_register_space

# Rebuild image (after updating dependencies in pyproject.toml)
./scripts/test.sh --rebuild
```

## Project Structure

```
llmflows/
├── cli/              # CLI commands (click)
│   └── mcp.py        # `llmflows connectors` commands
├── db/               # SQLAlchemy models (McpConnector, etc.) and Alembic migrations
├── services/         # Business logic (daemon, runs, flows, agents, gateway)
│   └── mcp.py        # MCP connector bridge (starts/stops connector servers)
├── tools/            # Built-in MCP servers (browser, web search) — TypeScript
├── ui/
│   ├── server.py     # FastAPI backend (includes connector catalog + API)
│   └── frontend/     # React + Vite frontend
├── defaults/         # Default config (config.toml) and setup flows
└── utils/            # Shared utilities
```

## Database Migrations

Migrations use Alembic and live in `llmflows/db/migrations/versions/`. Each migration is a numbered Python file.

To add a new migration:

1. Create a new file in `llmflows/db/migrations/versions/` following the naming convention (`0003_description.py`)
2. Use `op.batch_alter_table` for SQLite compatibility
3. The migration runs automatically on startup via `init_db()`

Example:

```python
"""add new column

Revision ID: 0003
Revises: 0002
"""
from alembic import op
import sqlalchemy as sa

revision: str = '0003'
down_revision = '0002'

def upgrade() -> None:
    with op.batch_alter_table('flows') as batch_op:
        batch_op.add_column(sa.Column('new_field', sa.String(100), nullable=True))

def downgrade() -> None:
    with op.batch_alter_table('flows') as batch_op:
        batch_op.drop_column('new_field')
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Run the test suite (`./scripts/test.sh`)
5. Open a pull request
