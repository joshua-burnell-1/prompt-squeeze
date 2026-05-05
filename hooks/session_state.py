# ABOUTME: Per-session consent state for the prompt-squeeze hook.
# ABOUTME: State lives at ~/.claude/prompt-squeeze/sessions/<session_hash>.json — three values: null, "yes-session", "no".

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

VALID_CONSENT = {"yes-session", "no"}


def _state_dir() -> Path:
    return Path.home() / ".claude" / "prompt-squeeze" / "sessions"


def _state_path(session_hash: str) -> Path:
    return _state_dir() / f"{session_hash}.json"


def read_consent(session_hash: str):
    """Return 'yes-session', 'no', or None (no decision yet / corrupt state)."""
    path = _state_path(session_hash)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        value = data.get("consent")
        if value in VALID_CONSENT:
            return value
        return None
    except (OSError, json.JSONDecodeError, ValueError):
        return None


def write_consent(session_hash: str, value: str) -> None:
    """Persist consent for this session. Atomic write via temp + rename."""
    if value not in VALID_CONSENT:
        raise ValueError(f"invalid consent value: {value!r}")
    state_dir = _state_dir()
    try:
        state_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            dir=str(state_dir),
            prefix=f".{session_hash}-",
            suffix=".tmp",
            delete=False,
            encoding="utf-8",
        ) as tmp:
            json.dump({"consent": value}, tmp)
            tmp_path = tmp.name
        os.replace(tmp_path, _state_path(session_hash))
    except OSError:
        return
