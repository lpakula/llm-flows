"""Tests for bundled Postgres and runner DATABASE_URL mapping."""

import os

import pytest

from llmflows.services.postgres import (
    PG_CONTAINER,
    default_host_database_url,
    runner_database_url,
)


def test_default_host_database_url():
    assert default_host_database_url() == "postgresql://llmflows:llmflows@localhost:5433/llmflows"


def test_runner_database_url_managed_postgres(monkeypatch):
    monkeypatch.setenv("LLMFLOWS_PG_CONTAINER", PG_CONTAINER)
    host = "postgresql://llmflows:llmflows@localhost:5433/llmflows"
    runner = runner_database_url(host)
    assert runner == f"postgresql://llmflows:llmflows@{PG_CONTAINER}:5432/llmflows"


def test_runner_database_url_external_localhost(monkeypatch):
    monkeypatch.delenv("LLMFLOWS_PG_CONTAINER", raising=False)
    host = "postgresql://user:pass@localhost:5432/mydb"
    assert runner_database_url(host) == "postgresql://user:pass@host.docker.internal:5432/mydb"


def test_runner_database_url_passthrough_remote(monkeypatch):
    monkeypatch.delenv("LLMFLOWS_PG_CONTAINER", raising=False)
    host = "postgresql://user:pass@db.example.com:5432/mydb"
    assert runner_database_url(host) == host


def test_build_env_args_uses_runner_database_url(monkeypatch):
    from unittest.mock import MagicMock, patch

    from llmflows.services import container as container_mod

    monkeypatch.setenv("DATABASE_URL", "postgresql://llmflows:llmflows@localhost:5433/llmflows")
    monkeypatch.setenv("LLMFLOWS_PG_CONTAINER", PG_CONTAINER)
    session = MagicMock()
    session.query.return_value.all.return_value = []
    with patch.object(container_mod, "get_session", return_value=session):
        args = container_mod._build_env_args(None)
    joined = " ".join(args)
    assert f"DATABASE_URL=postgresql://llmflows:llmflows@{PG_CONTAINER}:5432/llmflows" in joined


def test_get_database_url_rejects_sqlite(monkeypatch):
    from llmflows.db.database import _get_database_url

    monkeypatch.setenv("DATABASE_URL", "sqlite:////tmp/llmflows.db")
    with pytest.raises(RuntimeError, match="SQLite is no longer supported"):
        _get_database_url()
