# ABOUTME: Per-squeeze artifact writer for /sq explain deep-dive (Plan C of v0.4).
# ABOUTME: Local-only, secret-redacted, retention-capped at 100 entries, opt-in via prompt-squeeze.explain setting.

from __future__ import annotations

import json
import os
import shutil
import stat
import tempfile
from datetime import datetime, timezone  # noqa: UP017 — keeping 3.9 compat for hook
from pathlib import Path

import redaction

_RETENTION = 100


def _explain_dir() -> Path:
    return Path.home() / ".claude" / "prompt-squeeze" / "explain"


def _ensure_dir() -> Path:
    d = _explain_dir()
    d.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(d, 0o700)
    except OSError:
        pass
    return d


def _redact_rules(rules_fired: list[dict]) -> list[dict]:
    """Redact the 'removed' field of each rule hit (in case it captured secret text)."""
    out = []
    for hit in rules_fired or []:
        red = dict(hit)
        if "removed" in red and isinstance(red["removed"], str):
            red["removed"] = redaction.redact(red["removed"])
        out.append(red)
    return out


def _enforce_retention(d: Path) -> None:
    """Keep only the most recent _RETENTION files. Pruning is by mtime."""
    files = sorted(d.glob("*.json"), key=lambda p: p.stat().st_mtime)
    excess = len(files) - _RETENTION
    if excess > 0:
        for old in files[:excess]:
            try:
                old.unlink()
            except OSError:
                continue


def write_artifact(
    session_hash: str,
    seq: int,
    original_text: str,
    squeezed_text: str,
    tokens_original: int,
    tokens_squeezed: int,
    rules_fired: list,
) -> bool:
    """Write a per-squeeze artifact. Returns True on success, False on any I/O error."""
    try:
        d = _ensure_dir()
        artifact = {
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "session": session_hash,
            "seq": seq,
            "original_text": redaction.redact(original_text),
            "squeezed_text": redaction.redact(squeezed_text),
            "tokens_original": tokens_original,
            "tokens_squeezed": tokens_squeezed,
            "rules_fired": _redact_rules(rules_fired),
        }
        target = d / f"{session_hash}-{seq}.json"
        with tempfile.NamedTemporaryFile(
            mode="w",
            dir=str(d),
            prefix=f".{session_hash}-{seq}-",
            suffix=".tmp",
            delete=False,
            encoding="utf-8",
        ) as tmp:
            json.dump(artifact, tmp)
            tmp_path = tmp.name
        os.replace(tmp_path, target)
        try:
            os.chmod(target, stat.S_IRUSR | stat.S_IWUSR)  # 0600
        except OSError:
            pass
        _enforce_retention(d)
        return True
    except OSError:
        return False


def read_artifact(session_hash: str, relative_index: int = 0):
    """Read the (relative_index-th most recent) artifact for this session, or None."""
    d = _explain_dir()
    if not d.is_dir():
        return None
    matching = sorted(
        d.glob(f"{session_hash}-*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if relative_index >= len(matching):
        return None
    try:
        return json.loads(matching[relative_index].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return None


def list_artifacts(session_hash: str) -> list:
    """List all artifact filenames for this session, newest first."""
    d = _explain_dir()
    if not d.is_dir():
        return []
    return sorted(
        [p.name for p in d.glob(f"{session_hash}-*.json")],
        reverse=True,
    )


def disable() -> None:
    """Remove the entire explain directory (idempotent)."""
    d = _explain_dir()
    if d.exists():
        try:
            shutil.rmtree(d)
        except OSError:
            pass
