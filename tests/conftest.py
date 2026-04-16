"""Pytest configuration and fixtures."""

import subprocess
import tempfile
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from llmflows.db.models import Base, Space
from llmflows.db.database import reset_engine


@pytest.fixture(autouse=True)
def reset_database_engine():
    """Reset the global database engine before each test."""
    reset_engine()
    yield
    reset_engine()


@pytest.fixture
def temp_dir():
    """Create a temporary directory for tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def test_db():
    """Create an in-memory SQLite database for testing."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()
    Base.metadata.drop_all(engine)


@pytest.fixture
def test_space(test_db, temp_dir):
    """Create a test space in the database."""
    space = Space(name="test-space", path=str(temp_dir / "test-repo"))
    test_db.add(space)
    test_db.commit()
    return space


@pytest.fixture
def mock_git_repo(temp_dir):
    """Create a mock git repository for testing."""
    repo_dir = temp_dir / "test_repo"
    repo_dir.mkdir()
    subprocess.run(["git", "init"], cwd=repo_dir, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo_dir, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo_dir, capture_output=True)
    test_file = repo_dir / "test.txt"
    test_file.write_text("initial content")
    subprocess.run(["git", "add", "."], cwd=repo_dir, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo_dir, capture_output=True)
    return repo_dir
