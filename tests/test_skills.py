"""Tests for skill services, skillssh service, and skills API endpoints."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from llmflows.db.models import Base, Space
from llmflows.services.skill import SkillService, _parse_frontmatter
from llmflows.services.skillssh import (
    SkillsShService,
    parse_skill_ref,
    RegistrySkill,
)
from llmflows.services.space import SpaceService
from llmflows.ui.server import app


# ---------- Unit tests: parse_skill_ref ----------

class TestParseSkillRef:
    def test_at_separator(self):
        assert parse_skill_ref("owner/repo@skill") == ("owner", "repo", "skill")

    def test_slash_separator(self):
        assert parse_skill_ref("owner/repo/skill") == ("owner", "repo", "skill")

    def test_with_dashes_and_dots(self):
        assert parse_skill_ref("my-org/my.repo@my-skill") == ("my-org", "my.repo", "my-skill")

    def test_invalid_no_separator(self):
        assert parse_skill_ref("just-a-name") is None

    def test_invalid_empty(self):
        assert parse_skill_ref("") is None

    def test_whitespace_stripped(self):
        assert parse_skill_ref("  owner/repo@skill  ") == ("owner", "repo", "skill")


# ---------- Unit tests: SkillService ----------

class TestSkillService:
    def test_discover_empty(self, temp_dir):
        assert SkillService.discover(str(temp_dir)) == []

    def test_discover_finds_skills(self, temp_dir):
        skill_dir = temp_dir / ".agents" / "skills" / "my-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("---\ndescription: A test skill\n---\n# My Skill")

        skills = SkillService.discover(str(temp_dir))
        assert len(skills) == 1
        assert skills[0].name == "my-skill"
        assert skills[0].description == "A test skill"

    def test_discover_ignores_non_dirs(self, temp_dir):
        skills_root = temp_dir / ".agents" / "skills"
        skills_root.mkdir(parents=True)
        (skills_root / "not-a-skill.txt").write_text("nope")
        assert SkillService.discover(str(temp_dir)) == []

    def test_get_content(self, temp_dir):
        skill_dir = temp_dir / ".agents" / "skills" / "test"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("# Test Skill\nSome content")

        content = SkillService.get_content(str(temp_dir), "test")
        assert content is not None
        assert "# Test Skill" in content

    def test_get_content_missing(self, temp_dir):
        assert SkillService.get_content(str(temp_dir), "nonexistent") is None


# ---------- Unit tests: _parse_frontmatter ----------

class TestParseFrontmatter:
    def test_basic(self):
        text = "---\nname: test\ndescription: A skill\n---\n# Body"
        meta = _parse_frontmatter(text)
        assert meta["name"] == "test"
        assert meta["description"] == "A skill"

    def test_no_frontmatter(self):
        assert _parse_frontmatter("# Just a heading") == {}

    def test_incomplete_frontmatter(self):
        assert _parse_frontmatter("---\nname: test\n") == {}


# ---------- Unit tests: SkillsShService ----------

class TestSkillsShService:
    def test_install_creates_files(self, temp_dir):
        mock_content = "---\ndescription: Mock skill\n---\n# Mock"
        with patch.object(SkillsShService, "fetch_skill_md", return_value=mock_content):
            result = SkillsShService.install(str(temp_dir), "owner", "repo", "test-skill")

        assert result.success is True
        assert result.skill_name == "test-skill"

        skill_file = temp_dir / ".agents" / "skills" / "test-skill" / "SKILL.md"
        assert skill_file.is_file()
        assert "Mock skill" in skill_file.read_text()

        source_file = temp_dir / ".agents" / "skills" / "test-skill" / ".source"
        assert source_file.is_file()
        source = json.loads(source_file.read_text())
        assert source["slug"] == "owner/repo@test-skill"

    def test_install_failure(self, temp_dir):
        with patch.object(SkillsShService, "fetch_skill_md", return_value=None):
            result = SkillsShService.install(str(temp_dir), "owner", "repo", "missing")

        assert result.success is False
        assert "Could not fetch" in result.error

    def test_install_from_ref(self, temp_dir):
        mock_content = "# Installed via ref"
        with patch.object(SkillsShService, "fetch_skill_md", return_value=mock_content):
            result = SkillsShService.install_from_ref(str(temp_dir), "acme/tools@linter")

        assert result.success is True
        assert result.skill_name == "linter"

    def test_install_from_ref_invalid(self, temp_dir):
        result = SkillsShService.install_from_ref(str(temp_dir), "bad-ref")
        assert result.success is False
        assert "Invalid skill reference" in result.error

    def test_get_source_info(self, temp_dir):
        skill_dir = temp_dir / ".agents" / "skills" / "test"
        skill_dir.mkdir(parents=True)
        (skill_dir / ".source").write_text(json.dumps({
            "registry": "skills.sh", "slug": "a/b@test",
        }))
        info = SkillsShService.get_source_info(str(temp_dir), "test")
        assert info is not None
        assert info["slug"] == "a/b@test"

    def test_get_source_info_missing(self, temp_dir):
        assert SkillsShService.get_source_info(str(temp_dir), "nope") is None

    def test_list_with_sources(self, temp_dir):
        skill_dir = temp_dir / ".agents" / "skills" / "my-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("---\ndescription: Desc\n---\n# Content")
        (skill_dir / ".source").write_text(json.dumps({"slug": "o/r@my-skill"}))

        local_dir = temp_dir / ".agents" / "skills" / "local-skill"
        local_dir.mkdir(parents=True)
        (local_dir / "SKILL.md").write_text("# Local")

        result = SkillsShService.list_with_sources(str(temp_dir))
        assert len(result) == 2
        names = {r["name"] for r in result}
        assert "my-skill" in names
        assert "local-skill" in names
        remote = next(r for r in result if r["name"] == "my-skill")
        assert remote["source"]["slug"] == "o/r@my-skill"
        local = next(r for r in result if r["name"] == "local-skill")
        assert local["source"] is None

    def test_remove(self, temp_dir):
        skill_dir = temp_dir / ".agents" / "skills" / "rm-me"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("# Remove me")

        assert SkillsShService.remove(str(temp_dir), "rm-me") is True
        assert not skill_dir.exists()

    def test_remove_nonexistent(self, temp_dir):
        assert SkillsShService.remove(str(temp_dir), "nope") is False

    def test_search(self):
        mock_response = json.dumps({
            "query": "azure",
            "searchType": "fuzzy",
            "skills": [
                {
                    "id": "microsoft/azure-skills/azure-ai",
                    "skillId": "azure-ai",
                    "name": "azure-ai",
                    "installs": 50000,
                    "source": "microsoft/azure-skills",
                },
                {
                    "id": "user1/my-skills/testing",
                    "skillId": "testing",
                    "name": "testing",
                    "installs": 1200,
                    "source": "user1/my-skills",
                },
            ],
            "count": 2,
        }).encode()

        with patch("llmflows.services.skillssh._http_get", return_value=mock_response):
            results = SkillsShService.search("azure")

        assert len(results) == 2
        assert results[0].name == "azure-ai"
        assert results[0].owner == "microsoft"
        assert results[0].repo == "azure-skills"
        assert results[0].install_count == 50000
        assert results[1].name == "testing"
        assert results[1].owner == "user1"

    def test_search_sorted_by_install_count(self):
        mock_response = json.dumps({
            "skills": [
                {"skillId": "low", "name": "low", "installs": 10, "source": "a/b"},
                {"skillId": "high", "name": "high", "installs": 9999, "source": "c/d"},
                {"skillId": "mid", "name": "mid", "installs": 500, "source": "e/f"},
                {"skillId": "zero", "name": "zero", "installs": 0, "source": "g/h"},
            ],
            "count": 4,
        }).encode()

        with patch("llmflows.services.skillssh._http_get", return_value=mock_response):
            results = SkillsShService.search("test")

        assert [r.name for r in results] == ["high", "mid", "low", "zero"]
        assert [r.install_count for r in results] == [9999, 500, 10, 0]

    def test_search_github_delegates_to_search(self):
        mock_response = json.dumps({
            "skills": [{"skillId": "test-skill", "name": "test-skill",
                        "installs": 100, "source": "org/repo"}],
            "count": 1,
        }).encode()

        with patch("llmflows.services.skillssh._http_get", return_value=mock_response):
            results = SkillsShService.search_github("test")

        assert len(results) == 1
        assert results[0].name == "test-skill"

    def test_search_network_failure(self):
        with patch("llmflows.services.skillssh._http_get", return_value=None):
            results = SkillsShService.search("anything")
        assert results == []

    def test_search_respects_limit(self):
        mock_response = json.dumps({
            "skills": [
                {"skillId": f"skill-{i}", "name": f"skill-{i}",
                 "installs": i, "source": "org/repo"}
                for i in range(10)
            ],
            "count": 10,
        }).encode()

        with patch("llmflows.services.skillssh._http_get", return_value=mock_response):
            results = SkillsShService.search("test", limit=3)

        assert len(results) == 3


# ---------- API tests ----------

@pytest.fixture
def skills_api_db():
    """Set up a shared in-memory DB and patch the server to use it."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    setup_session = Session()
    with tempfile.TemporaryDirectory() as tmpdir:
        space = Space(name="skill-test-space", path=tmpdir)
        setup_session.add(space)
        setup_session.flush()
        space_id = space.id
        setup_session.commit()
        setup_session.close()

        skill_dir = Path(tmpdir) / ".agents" / "skills" / "local-test"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("---\ndescription: A local skill\n---\n# Local Test")

        def mock_get_services():
            s = Session()
            return s, SpaceService(s)

        with patch("llmflows.ui.server._get_services", mock_get_services):
            yield {"space_id": space_id, "tmpdir": tmpdir}

    Base.metadata.drop_all(engine)


@pytest.fixture
def skills_client(skills_api_db):
    return TestClient(app)


class TestSkillsAPI:
    def test_list_skills(self, skills_client, skills_api_db):
        resp = skills_client.get(f"/api/spaces/{skills_api_db['space_id']}/skills")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["name"] == "local-test"
        assert data[0]["description"] == "A local skill"
        assert data[0]["source"] is None

    def test_get_skill_content(self, skills_client, skills_api_db):
        resp = skills_client.get(f"/api/spaces/{skills_api_db['space_id']}/skills/local-test/content")
        assert resp.status_code == 200
        assert "# Local Test" in resp.json()["content"]

    def test_get_skill_content_not_found(self, skills_client, skills_api_db):
        resp = skills_client.get(f"/api/spaces/{skills_api_db['space_id']}/skills/nope/content")
        assert resp.status_code == 404

    def test_install_skill(self, skills_client, skills_api_db):
        mock_content = "---\ndescription: Installed\n---\n# New"
        with patch.object(SkillsShService, "fetch_skill_md", return_value=mock_content):
            resp = skills_client.post(
                f"/api/spaces/{skills_api_db['space_id']}/skills/install",
                json={"source": "acme/tools@new-skill"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["skill_name"] == "new-skill"

        skill_file = Path(skills_api_db["tmpdir"]) / ".agents" / "skills" / "new-skill" / "SKILL.md"
        assert skill_file.is_file()

    def test_install_skill_invalid_ref(self, skills_client, skills_api_db):
        resp = skills_client.post(
            f"/api/spaces/{skills_api_db['space_id']}/skills/install",
            json={"source": "bad"},
        )
        assert resp.status_code == 400

    def test_install_skill_fetch_fails(self, skills_client, skills_api_db):
        with patch.object(SkillsShService, "fetch_skill_md", return_value=None):
            resp = skills_client.post(
                f"/api/spaces/{skills_api_db['space_id']}/skills/install",
                json={"source": "owner/repo@missing"},
            )
        assert resp.status_code == 400

    def test_remove_skill(self, skills_client, skills_api_db):
        resp = skills_client.delete(f"/api/spaces/{skills_api_db['space_id']}/skills/local-test")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

        skill_dir = Path(skills_api_db["tmpdir"]) / ".agents" / "skills" / "local-test"
        assert not skill_dir.exists()

    def test_remove_skill_not_found(self, skills_client, skills_api_db):
        resp = skills_client.delete(f"/api/spaces/{skills_api_db['space_id']}/skills/nope")
        assert resp.status_code == 404

    def test_search_skills(self, skills_client, skills_api_db):
        mock_response = json.dumps({
            "skills": [{
                "skillId": "testing",
                "name": "testing",
                "installs": 5000,
                "source": "acme/skills",
            }],
            "count": 1,
        }).encode()

        with patch("llmflows.services.skillssh._http_get", return_value=mock_response):
            resp = skills_client.get("/api/skills/search?q=testing")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["name"] == "testing"
        assert data[0]["slug"] == "acme/skills@testing"
        assert data[0]["install_count"] == 5000

    def test_search_skills_sorted_by_installs(self, skills_client, skills_api_db):
        mock_response = json.dumps({
            "skills": [
                {"skillId": "few", "name": "few", "installs": 5, "source": "a/b"},
                {"skillId": "many", "name": "many", "installs": 10000, "source": "c/d"},
                {"skillId": "some", "name": "some", "installs": 200, "source": "e/f"},
            ],
            "count": 3,
        }).encode()

        with patch("llmflows.services.skillssh._http_get", return_value=mock_response):
            resp = skills_client.get("/api/skills/search?q=test")

        assert resp.status_code == 200
        data = resp.json()
        assert [s["name"] for s in data] == ["many", "some", "few"]
        assert [s["install_count"] for s in data] == [10000, 200, 5]

    def test_search_skills_empty_query(self, skills_client, skills_api_db):
        resp = skills_client.get("/api/skills/search?q=")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_skills_space_not_found(self, skills_client, skills_api_db):
        resp = skills_client.get("/api/spaces/nonexistent/skills")
        assert resp.status_code == 404
