# ABOUTME: Pending-squeeze cache for /sq y/n/undo recovery commands.
# ABOUTME: Keyed by session hash; one entry per session at a time. Atomic writes.

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone  # noqa: UP017 — keeping 3.9 compat for hook
from pathlib import Path


def _cache_path() -> Path:
    return Path.home() / ".claude" / "prompt-squeeze" / "pending.json"


def _read_all() -> dict:
    path = _cache_path()
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return {}


def _write_all(data: dict) -> None:
    path = _cache_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            dir=str(path.parent),
            prefix=".pending-",
            suffix=".tmp",
            delete=False,
            encoding="utf-8",
        ) as tmp:
            json.dump(data, tmp)
            tmp_path = tmp.name
        os.replace(tmp_path, path)
    except OSError:
        return


def write_pending(
    session_hash: str,
    seq: int,
    original_text: str,
    squeezed_text: str,
    tokens_original: int,
    tokens_squeezed: int,
    saved_dollars: float,
    saved_wh: float,
    store_original: bool,
) -> None:
    """Write a pending squeeze entry keyed by session_hash. Overwrites any prior entry."""
    data = _read_all()
    entry = {
        "seq": seq,
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "squeezed_text": squeezed_text,
        "tokens_original": tokens_original,
        "tokens_squeezed": tokens_squeezed,
        "saved_dollars": saved_dollars,
        "saved_wh": saved_wh,
        "consumed": False,
    }
    if store_original:
        entry["original_text"] = original_text
    data[session_hash] = entry
    _write_all(data)


def read_pending(session_hash: str):
    """Return the latest pending entry for this session, or None."""
    data = _read_all()
    entry = data.get(session_hash)
    if not entry:
        return None
    return entry


def mark_consumed(session_hash: str) -> None:
    """Mark the most recent entry consumed."""
    data = _read_all()
    if session_hash in data:
        data[session_hash]["consumed"] = True
        _write_all(data)
