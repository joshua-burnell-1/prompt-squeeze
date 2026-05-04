# ABOUTME: Validates plugin manifest (.claude-plugin/plugin.json) and hooks.json structure.
# ABOUTME: These are required for Claude Code to load the plugin.

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
MANIFEST = REPO / ".claude-plugin" / "plugin.json"
HOOKS = REPO / "hooks" / "hooks.json"


def test_manifest_exists():
    assert MANIFEST.exists()


def test_manifest_is_valid_json():
    json.loads(MANIFEST.read_text())


def test_manifest_required_fields():
    data = json.loads(MANIFEST.read_text())
    for k in ("name", "version", "description", "author"):
        assert k in data
    assert data["name"] == "prompt-squeeze"


def test_hooks_file_exists():
    """Claude Code auto-loads hooks/hooks.json; the manifest must NOT list it
    explicitly (that triggers a duplicate-hooks-file load error). Just verify
    the well-known path exists."""
    assert HOOKS.exists(), "hooks/hooks.json must exist for auto-load"


def test_manifest_declares_mcp_server():
    data = json.loads(MANIFEST.read_text())
    assert "mcpServers" in data
    assert "prompt-squeeze-stats" in data["mcpServers"]


def test_hooks_json_valid():
    data = json.loads(HOOKS.read_text())
    assert "hooks" in data
    assert "UserPromptSubmit" in data["hooks"]


def test_hooks_json_has_timeout():
    data = json.loads(HOOKS.read_text())
    entries = data["hooks"]["UserPromptSubmit"]
    assert isinstance(entries, list) and len(entries) >= 1
    # Claude Code hooks shape: [{matcher, hooks: [{type, command, timeout}]}]
    # Timeout must be set so the hook can't hang the user's prompt flow.
    found = False
    for matcher_entry in entries:
        for cmd_entry in matcher_entry.get("hooks", []):
            if "timeout" in cmd_entry:
                assert cmd_entry["timeout"] <= 10
                found = True
    assert found, "UserPromptSubmit command entry should declare a timeout"
