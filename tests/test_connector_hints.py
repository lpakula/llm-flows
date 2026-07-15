"""Tests for connector tool hints."""

from llmflows.services.connector_hints import build_tools_section


def test_build_tools_section_for_flow_step_forbids_shell_substitution():
    section = build_tools_section(["github"], for_flow_step=True)
    assert "list_commits" in section
    assert "git clone" in section
    assert "Do **not** substitute bash" in section
