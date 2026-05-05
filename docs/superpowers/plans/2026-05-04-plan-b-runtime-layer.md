<!-- ABOUTME: Plan B — implementation plan for the v0.4 runtime layer (Components 2 + 3 of the spec). -->
<!-- ABOUTME: Hook flips to interactive blocking by default, consent state machine, pending cache, /sq slash commands. -->

# Plan B — Runtime Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert the `UserPromptSubmit` hook from advise-mode-by-default to interactive-blocking-by-default so token savings become real (not aspirational), wire in a one-time-per-session consent flow, and ship the `/sq y/n/undo/off` slash commands that resume from a pending-squeeze cache.

**Architecture:** The hook now writes a pending-squeeze entry keyed by session hash on every block, alongside a session consent state. Slash commands read the cache and emit the appropriate text (squeezed or original) as the next user message. Consent has three states (`null` / `"yes-session"` / `"no"`); the hook short-circuits when consent is `"no"`.

**Tech Stack:** Python 3.9-compatible (the hook runs under macOS system Python), stdlib-only. Slash commands are markdown files instructing Claude to read the cache file. New filesystem state under `~/.claude/prompt-squeeze/`.

**Spec reference:** [docs/superpowers/specs/2026-05-04-prompt-squeeze-v04-design.md](docs/superpowers/specs/2026-05-04-prompt-squeeze-v04-design.md), Components 2 + 3.

**Depends on:** Plan A (compression layer with rule registry).

---

## Scope check

This plan covers Components 2 and 3 of the spec. They're tightly coupled (the hook writes to the cache; the slash commands read from it), so they're in one plan rather than two. Plan C (introspection / explain) and Plan D (status line / awareness) come after.

## File structure

| File | Status | Responsibility |
|---|---|---|
| `hooks/user_prompt_submit.py` | Modify | Default `mode` flips to `interactive`; consent state read/write; pending cache write; transcript-visible block message scaled to consent state. |
| `hooks/session_state.py` | **Create** | Tiny helper module: read/write session consent JSON, atomic writes, corrupt-state recovery. Imported by the hook. |
| `hooks/pending_cache.py` | **Create** | Tiny helper module: read/write the pending-squeeze cache, mark-consumed semantics. Imported by the hook AND the slash commands' executor (via Read+Bash). |
| `commands/sq.md` | **Create** | Single dispatch slash command: `/sq y` / `/sq n` / `/sq undo` / `/sq off`. Body instructs Claude to invoke a small Python helper that reads the cache and emits text. |
| `commands/squeeze.md` | Modify | Update install instructions and reference the new flow. |
| `settings.schema.json` | Modify | Add `block_threshold` (default 500), update `mode` enum, deprecate `interactive` (folded into mode), document `warn_threshold` removal. |
| `tests/plugin/test_hook.py` | Modify | Add tests for each consent state, pending-cache write, terse-vs-full banner. |
| `tests/plugin/test_session_state.py` | **Create** | Unit tests for the session-state helper. |
| `tests/plugin/test_pending_cache.py` | **Create** | Unit tests for the pending-cache helper. |
| `tests/integration/test_block_recovery_flow.py` | **Create** | End-to-end: hook block → cache write → cache read returns expected text. |
| `README.md` | Modify | Document the new default behavior, escape hatches, and migration from v0.3. |

**Why split helpers into their own files:** the hook is already large (~600 lines) and runs under restricted Python (3.9, stdlib-only). Splitting session-state and pending-cache into focused modules lets each be unit-tested in isolation and keeps the hook focused on its decision logic.

---

## Task 1: Session-state helper

Manages consent state per session, persisted under `~/.claude/prompt-squeeze/sessions/<session_hash>.json`.

**Files:**
- Create: `hooks/session_state.py`
- Create: `tests/plugin/test_session_state.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/plugin/test_session_state.py`:

```python
# ABOUTME: Tests for session_state — read/write consent state per session, atomic writes, recovery.
# ABOUTME: The hook uses these to remember user consent across multiple prompts in one session.

import json

import session_state  # noqa: E402 (added to sys.path by conftest)


class TestSessionState:
    def test_read_returns_null_for_new_session(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        state = session_state.read_consent("abc123")
        assert state is None

    def test_write_then_read(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        session_state.write_consent("abc123", "yes-session")
        assert session_state.read_consent("abc123") == "yes-session"

    def test_write_no_consent(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        session_state.write_consent("abc123", "no")
        assert session_state.read_consent("abc123") == "no"

    def test_overwrite(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        session_state.write_consent("abc123", "yes-session")
        session_state.write_consent("abc123", "no")
        assert session_state.read_consent("abc123") == "no"

    def test_isolation_between_sessions(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        session_state.write_consent("abc123", "yes-session")
        session_state.write_consent("def456", "no")
        assert session_state.read_consent("abc123") == "yes-session"
        assert session_state.read_consent("def456") == "no"

    def test_corrupt_state_recovers_to_null(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        path = tmp_path / ".claude" / "prompt-squeeze" / "sessions" / "abc123.json"
        path.parent.mkdir(parents=True)
        path.write_text("{not valid json")
        # Corrupt state must not raise — return null and let hook treat as fresh.
        assert session_state.read_consent("abc123") is None

    def test_invalid_value_treated_as_null(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        path = tmp_path / ".claude" / "prompt-squeeze" / "sessions" / "abc123.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"consent": "invalid-value"}))
        assert session_state.read_consent("abc123") is None
```

- [ ] **Step 2: Run, expect ImportError**

Run: `cd ~/projects/prompt-squeeze && uv run pytest tests/plugin/test_session_state.py -v 2>&1 | tail -5`
Expected: ImportError / collection error.

- [ ] **Step 3: Implement the helper**

Create `hooks/session_state.py`:

```python
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


def read_consent(session_hash: str) -> str | None:
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
        # Atomic write: write to temp file in same dir, then rename.
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
        # Best effort — if we can't write, the next prompt just gets the full banner again.
        return
```

- [ ] **Step 4: Run tests, expect pass**

Run: `cd ~/projects/prompt-squeeze && uv run pytest tests/plugin/test_session_state.py -v 2>&1 | tail -10`
Expected: 7 PASS.

- [ ] **Step 5: Commit**

```bash
git add hooks/session_state.py tests/plugin/test_session_state.py
git commit -m "Add per-session consent state helper for prompt-squeeze hook"
```

---

## Task 2: Pending-cache helper

Stores the most recent squeeze per session so `/sq y/n/undo` can resume from it.

**Files:**
- Create: `hooks/pending_cache.py`
- Create: `tests/plugin/test_pending_cache.py`

- [ ] **Step 1: Write failing tests**

Create `tests/plugin/test_pending_cache.py`:

```python
# ABOUTME: Tests for pending_cache — write/read/consume a single pending squeeze per session.
# ABOUTME: Drives /sq y/n/undo recovery; cache lives at ~/.claude/prompt-squeeze/pending.json.

import pending_cache  # noqa: E402 (added to sys.path by conftest)


class TestPendingCache:
    def test_read_returns_none_when_no_entry(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        assert pending_cache.read_pending("abc123") is None

    def test_write_then_read(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        pending_cache.write_pending(
            session_hash="abc123",
            seq=1,
            original_text="please fix foo.py",
            squeezed_text="fix foo.py",
            tokens_original=10,
            tokens_squeezed=5,
            saved_dollars=0.0001,
            saved_wh=0.05,
            store_original=False,
        )
        entry = pending_cache.read_pending("abc123")
        assert entry["squeezed_text"] == "fix foo.py"
        assert entry["seq"] == 1
        assert entry["consumed"] is False
        # original_text omitted when store_original=False
        assert "original_text" not in entry or entry["original_text"] is None

    def test_write_with_original_stored_when_explain_on(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        pending_cache.write_pending(
            session_hash="abc123",
            seq=1,
            original_text="please fix foo.py",
            squeezed_text="fix foo.py",
            tokens_original=10,
            tokens_squeezed=5,
            saved_dollars=0.0001,
            saved_wh=0.05,
            store_original=True,
        )
        entry = pending_cache.read_pending("abc123")
        assert entry["original_text"] == "please fix foo.py"

    def test_mark_consumed(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        pending_cache.write_pending(
            session_hash="abc123", seq=1,
            original_text="x", squeezed_text="y",
            tokens_original=1, tokens_squeezed=1,
            saved_dollars=0.0, saved_wh=0.0, store_original=True,
        )
        pending_cache.mark_consumed("abc123")
        entry = pending_cache.read_pending("abc123")
        assert entry["consumed"] is True

    def test_isolation_between_sessions(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        pending_cache.write_pending("abc123", 1, "a", "b", 1, 1, 0.0, 0.0, False)
        pending_cache.write_pending("def456", 2, "c", "d", 1, 1, 0.0, 0.0, False)
        assert pending_cache.read_pending("abc123")["squeezed_text"] == "b"
        assert pending_cache.read_pending("def456")["squeezed_text"] == "d"

    def test_overwrite_replaces_entry(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        pending_cache.write_pending("abc123", 1, "a", "b", 1, 1, 0.0, 0.0, False)
        pending_cache.write_pending("abc123", 2, "c", "d", 1, 1, 0.0, 0.0, False)
        entry = pending_cache.read_pending("abc123")
        assert entry["seq"] == 2
        assert entry["squeezed_text"] == "d"
```

- [ ] **Step 2: Run, expect fail**

Run: `cd ~/projects/prompt-squeeze && uv run pytest tests/plugin/test_pending_cache.py -v 2>&1 | tail -5`
Expected: ImportError.

- [ ] **Step 3: Implement the helper**

Create `hooks/pending_cache.py`:

```python
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


def read_pending(session_hash: str) -> dict | None:
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
```

- [ ] **Step 4: Run tests, expect pass**

Run: `cd ~/projects/prompt-squeeze && uv run pytest tests/plugin/test_pending_cache.py -v 2>&1 | tail -10`
Expected: 6 PASS.

- [ ] **Step 5: Commit**

```bash
git add hooks/pending_cache.py tests/plugin/test_pending_cache.py
git commit -m "Add pending-squeeze cache helper for /sq y/n/undo recovery"
```

---

## Task 3: Hook integration — read consent + write pending cache

Modify the hook to use both helpers. Behavior change is small at this step — we still log + nudge as v0.3 does. The new behavior (default-block) lands in Task 4. This task wires the plumbing without flipping the default.

**Files:**
- Modify: `hooks/user_prompt_submit.py`
- Modify: `tests/plugin/test_hook.py`

- [ ] **Step 1: Add imports + helper calls in the hook (no behavior change yet)**

Read [hooks/user_prompt_submit.py](hooks/user_prompt_submit.py:1-50). Add after the existing imports (around line 14):

```python
sys.path.insert(0, str(Path(__file__).resolve().parent))
import session_state  # noqa: E402
import pending_cache  # noqa: E402
```

In `_process()` after the prompt is read and tokenized but before the threshold check, add session-consent read:

```python
    consent = session_state.read_consent(session_hash)
    base_log["consent"] = consent  # for diagnostics
```

- [ ] **Step 2: Existing tests should still pass (no behavior change yet)**

Run: `cd ~/projects/prompt-squeeze && uv run pytest tests/ 2>&1 | tail -2`
Expected: same count as Plan A end-state (~157+ tests passing).

- [ ] **Step 3: Commit**

```bash
git add hooks/user_prompt_submit.py
git commit -m "Wire session_state + pending_cache helpers into hook (no behavior change)"
```

---

## Task 4: Flip hook default to interactive blocking

The big behavior change. `mode` default → `"interactive"`, `block_threshold` default 500, hook returns `decision: block` with reason scaled to consent state.

**Files:**
- Modify: `hooks/user_prompt_submit.py:21-30` (DEFAULT_SETTINGS)
- Modify: `hooks/user_prompt_submit.py` (_process function)
- Modify: `tests/plugin/test_hook.py`

- [ ] **Step 1: Write failing tests for the new behavior**

Add to `tests/plugin/test_hook.py`:

```python
class TestInteractiveBlockDefault:
    def test_long_prompt_with_no_consent_blocks_with_full_banner(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        # Build a payload with a >500-token prompt
        long_prompt = "Please could you " + "explain " * 250
        payload = {
            "session_id": "test_session_1",
            "cwd": str(tmp_path),
            "prompt": long_prompt,
        }
        from user_prompt_submit import _process
        result = _process(payload)
        out = result["output"]
        assert out.get("decision") == "block"
        assert "yes-session" in out.get("reason", "")  # full banner mentions yes-session option
        assert "/sq y" in out.get("reason", "")

    def test_long_prompt_with_yes_session_consent_blocks_with_terse_banner(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        import session_state
        session_hash = "test_session_2"  # before hashing — but the hook uses session_id hash
        # Need to hash same way the hook does: sha256(session_id)[:16]
        import hashlib
        sid = "test_session_2"
        sh = hashlib.sha256(sid.encode()).hexdigest()[:16]
        session_state.write_consent(sh, "yes-session")

        long_prompt = "Please could you " + "explain " * 250
        payload = {
            "session_id": sid,
            "cwd": str(tmp_path),
            "prompt": long_prompt,
        }
        from user_prompt_submit import _process
        result = _process(payload)
        out = result["output"]
        assert out.get("decision") == "block"
        # Terse banner: shorter, no 'yes-session' option (already opted in)
        assert "yes-session" not in out.get("reason", "")
        assert "/sq y" in out.get("reason", "")

    def test_long_prompt_with_no_consent_passes_through(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        import session_state
        import hashlib
        sid = "test_session_3"
        sh = hashlib.sha256(sid.encode()).hexdigest()[:16]
        session_state.write_consent(sh, "no")

        long_prompt = "Please could you " + "explain " * 250
        payload = {
            "session_id": sid,
            "cwd": str(tmp_path),
            "prompt": long_prompt,
        }
        from user_prompt_submit import _process
        result = _process(payload)
        # User opted out — no block, just a measurement log
        assert "decision" not in result["output"]

    def test_short_prompt_does_not_block(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        payload = {
            "session_id": "test_session_4",
            "cwd": str(tmp_path),
            "prompt": "fix foo.py",
        }
        from user_prompt_submit import _process
        result = _process(payload)
        # Below threshold — no block
        assert "decision" not in result["output"]

    def test_block_writes_pending_cache(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        import pending_cache
        import hashlib
        sid = "test_session_5"
        sh = hashlib.sha256(sid.encode()).hexdigest()[:16]
        long_prompt = "Please could you " + "explain " * 250
        payload = {
            "session_id": sid,
            "cwd": str(tmp_path),
            "prompt": long_prompt,
        }
        from user_prompt_submit import _process
        _process(payload)
        entry = pending_cache.read_pending(sh)
        assert entry is not None
        assert "squeezed_text" in entry
```

- [ ] **Step 2: Run, expect failures (default mode is still 'advise', threshold 800)**

Run: `cd ~/projects/prompt-squeeze && uv run pytest tests/plugin/test_hook.py::TestInteractiveBlockDefault -v 2>&1 | tail -20`
Expected: 4-5 FAILS.

- [ ] **Step 3: Update DEFAULT_SETTINGS**

Edit `hooks/user_prompt_submit.py`. Replace lines 21-30:

```python
DEFAULT_SETTINGS = {
    "mode": "interactive",          # v0.4 default flip from "advise"
    "block_threshold": 500,          # v0.4: prompts above this are blocked + offered for squeeze
    "warn_threshold": 800,           # legacy, retained for non-interactive nudges
    "notify_threshold": 0.25,
    "hard_limit": 4000,
    "interactive": False,             # legacy, ignored when mode=="interactive"
    "telemetry": "local",
    "model_override": None,
    "team_endpoint": None,
    "explain": "off",                 # v0.4: per-squeeze artifact opt-in for /sq explain (Plan C)
}
```

- [ ] **Step 4: Update `_process()` to honor the new mode + write pending cache + return block**

Replace the threshold-and-decision block in `_process()` (around lines 254-341) with:

```python
    # Mode dispatch
    mode = settings.get("mode", "interactive")
    block_threshold = settings.get("block_threshold", 500)

    if mode == "off":
        return {"output": {}, "log": base_log}

    consent = session_state.read_consent(session_hash)
    base_log["consent"] = consent

    # User opted out for this session — no block, log measurement only.
    if consent == "no":
        base_log["action"] = "consent_no"
        return {"output": {}, "log": base_log}

    # Below threshold — no compression, just measurement.
    if original_tokens < block_threshold:
        return {"output": {}, "log": base_log}

    if (time.monotonic() - started) * 1000 > WALL_BUDGET_MS:
        base_log["action"] = "hook_timeout"
        return {"output": {}, "log": base_log}

    # Compress
    compress_mod, estimate_mod = _import_skill()
    if compress_mod and hasattr(compress_mod, "compress"):
        try:
            compressed_text = compress_mod.compress(prompt)
        except Exception:
            compressed_text = _fallback_compress(prompt)
    else:
        compressed_text = _fallback_compress(prompt)

    compressed_tokens = _tokenize(compressed_text) if compressed_text else original_tokens
    if compressed_tokens > original_tokens:
        compressed_tokens = original_tokens

    saved_tokens = max(0, original_tokens - compressed_tokens)
    achievable_pct = saved_tokens / original_tokens if original_tokens else 0.0

    if estimate_mod and hasattr(estimate_mod, "estimate"):
        try:
            receipt = estimate_mod.estimate(
                original_tokens=original_tokens,
                compressed_tokens=compressed_tokens,
                model=model,
            )
        except Exception:
            receipt = _fallback_estimate(original_tokens, compressed_tokens, model)
    else:
        receipt = _fallback_estimate(original_tokens, compressed_tokens, model)

    dollars = float(receipt.get("saved_dollars", 0.0) or 0.0)
    wh = float(receipt.get("saved_wh", 0.0) or 0.0)

    base_log.update({
        "achievable_tokens": saved_tokens,
        "achievable_pct": round(achievable_pct, 4),
        "estimated_dollars_saved": round(dollars, 6),
        "estimated_wh_saved": round(wh, 4),
    })

    # Mode == "advise" — legacy v0.3 behavior
    if mode == "advise":
        if achievable_pct < settings.get("notify_threshold", 0.25):
            base_log["action"] = "silent"
            return {"output": {}, "log": base_log}
        base_log["action"] = "nudge"
        msg = _nudge_message(original_tokens, saved_tokens, dollars, wh)
        return {
            "output": {
                "hookSpecificOutput": {
                    "hookEventName": "UserPromptSubmit",
                    "additionalContext": msg,
                }
            },
            "log": base_log,
        }

    # Mode == "interactive" — block and write pending cache
    explain_on = settings.get("explain", "off") == "on"
    seq = _next_seq(session_hash)
    pending_cache.write_pending(
        session_hash=session_hash,
        seq=seq,
        original_text=prompt,
        squeezed_text=compressed_text,
        tokens_original=original_tokens,
        tokens_squeezed=compressed_tokens,
        saved_dollars=dollars,
        saved_wh=wh,
        store_original=explain_on,
    )

    if consent == "yes-session":
        base_log["action"] = "block_terse"
        reason = (
            f"auto: {original_tokens} -> {compressed_tokens} tok "
            f"(-{achievable_pct:.0%}) saved ${dollars:.4f}, {wh:.2f} Wh\n"
            f"/sq y to send squeezed, /sq n to send original"
        )
    else:
        # No consent yet — full banner with side-by-side
        base_log["action"] = "block_full_banner"
        diff = _side_by_side(
            prompt,
            compressed_text,
            original_label=f"ORIGINAL ({original_tokens} tok)",
            compressed_label=f"COMPRESSED ({compressed_tokens} tok, -{achievable_pct:.0%})",
        )
        reason = (
            f"prompt-squeeze: your prompt is {original_tokens} tokens. "
            f"A compressed version saves {saved_tokens} tokens "
            f"(~${dollars:.4f}, ~{wh:.2f} Wh).\n\n"
            f"{diff}\n\n"
            "Reply with one of:\n"
            "  /sq y          send the squeezed version once\n"
            "  /sq y session  send squeezed AND auto-confirm for the rest of this session\n"
            "  /sq n          send your original prompt unchanged"
        )

    return {
        "output": {"decision": "block", "reason": reason},
        "log": base_log,
    }
```

Add a helper `_next_seq()` near the top of the file:

```python
def _next_seq(session_hash: str) -> int:
    """Return the next sequence number for this session by reading the latest pending entry."""
    try:
        existing = pending_cache.read_pending(session_hash)
        if existing:
            return int(existing.get("seq", 0)) + 1
    except Exception:
        pass
    return 1
```

- [ ] **Step 5: Run the new tests, expect pass**

Run: `cd ~/projects/prompt-squeeze && uv run pytest tests/plugin/test_hook.py::TestInteractiveBlockDefault -v 2>&1 | tail -15`
Expected: 5 PASS.

- [ ] **Step 6: Run the full suite — some existing v0.3 hook tests may need updating**

Run: `cd ~/projects/prompt-squeeze && uv run pytest tests/ 2>&1 | tail -3`
Expected: most pass; some v0.3 hook tests that asserted advise-mode behavior need updating to either set `mode: "advise"` explicitly or be retitled to test the new default. Update them inline.

- [ ] **Step 7: Commit**

```bash
git add hooks/user_prompt_submit.py tests/plugin/test_hook.py
git commit -m "Flip hook default to interactive blocking (block_threshold=500, mode='interactive')"
```

---

## Task 5: `/sq` slash command — single dispatch

One slash command file that handles `y`, `n`, `undo`, `off`. Body instructs Claude to read the cache via `Read` and emit text or update consent.

**Files:**
- Create: `commands/sq.md`

- [ ] **Step 1: Write the slash command file**

Create `commands/sq.md`:

```markdown
---
name: sq
description: Resume a pending squeeze (y/n) or manage session consent (undo/off)
argument-hint: "[y|y session|n|undo|off]"
---

<!-- ABOUTME: /sq dispatches the y/n/undo/off subcommands for the prompt-squeeze interactive flow. -->
<!-- ABOUTME: Reads ~/.claude/prompt-squeeze/pending.json + writes session_state to manage consent. -->

You are responding to the user's `/sq` command. The argument is `$1` (with optional `$2`).

The cache file is at `~/.claude/prompt-squeeze/pending.json`. The current session's hash is in the most recent UserPromptSubmit hook output you saw — it's the SHA-256-prefix-16 of the session id. If you don't have access to the session id, you can find the most recently written entry by inspecting the cache.

Branch on the argument:

**If `$1 == "y"`:** Read the cache, find the most recent unconsumed entry. Submit `squeezed_text` as the next user message verbatim (no preamble, no quoting, no commentary — just the squeezed text). Then run a Bash command to mark the entry consumed: `python3 -c "import sys, json; from pathlib import Path; p=Path.home()/'.claude'/'prompt-squeeze'/'pending.json'; d=json.loads(p.read_text()); k=list(d.keys())[-1]; d[k]['consumed']=True; p.write_text(json.dumps(d))"`.

**If `$1 == "y" and $2 == "session"`:** Same as `y`, AND write session consent. Run: `python3 -c "from pathlib import Path; import json, os, tempfile; ..."` — or use `Edit` on `~/.claude/prompt-squeeze/sessions/<hash>.json` with content `{"consent": "yes-session"}`.

**If `$1 == "n"`:** Read the cache. If `original_text` is present, submit it. If absent, tell the user: "Original prompt was not stored (explain feature is off — turn it on with `/sq explain on` to enable undo). Please retype your prompt." Then mark consumed.

**If `$1 == "undo"`:** Read the cache, find the most recent CONSUMED entry. Submit its `original_text` (requires explain enabled). Tell the user "resending original" before submitting.

**If `$1 == "off"`:** Write `{"consent": "no"}` to `~/.claude/prompt-squeeze/sessions/<hash>.json`. Tell the user "prompt-squeeze disabled for the rest of this session. /sq y/n still work for the pending entry; new prompts will pass through unchanged."

**If `$1` is missing or unknown:** Show the user: "Usage: `/sq y` (send squeezed) | `/sq y session` (send squeezed + auto-confirm rest of session) | `/sq n` (send original) | `/sq undo` (resend last as original) | `/sq off` (disable for session)".

Never echo the squeezed/original prompt back to the user as commentary — just submit it as the next user message.
```

- [ ] **Step 2: Sanity check the slash command exists**

Run: `cd ~/projects/prompt-squeeze && cat commands/sq.md | head -10`
Expected: file content above.

- [ ] **Step 3: Commit**

```bash
git add commands/sq.md
git commit -m "Add /sq dispatch slash command for resume/cancel/undo/off"
```

---

## Task 6: Settings schema update

Update `settings.schema.json` to document the new keys and deprecations.

**Files:**
- Modify: `settings.schema.json`
- Modify: `tests/skill/test_data_files.py` (if it validates the schema)

- [ ] **Step 1: Update the schema**

Edit `settings.schema.json`. Replace the existing schema with:

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "prompt-squeeze settings",
  "type": "object",
  "properties": {
    "prompt-squeeze.mode": {
      "type": "string",
      "enum": ["off", "advise", "interactive"],
      "default": "interactive",
      "description": "off: hook disabled. advise: nudge Claude to /squeeze (v0.3 behavior). interactive: block prompts above block_threshold and offer /sq y/n (v0.4 default)."
    },
    "prompt-squeeze.block_threshold": {
      "type": "integer",
      "default": 500,
      "minimum": 0,
      "description": "v0.4: prompts above this token count are blocked in interactive mode. Default 500."
    },
    "prompt-squeeze.warn_threshold": {
      "type": "integer",
      "default": 800,
      "deprecated": true,
      "description": "Legacy v0.3 advise-mode threshold. Ignored when mode is 'interactive'."
    },
    "prompt-squeeze.notify_threshold": {
      "type": "number",
      "default": 0.25,
      "description": "Minimum compressible fraction to emit a nudge in advise mode."
    },
    "prompt-squeeze.hard_limit": {
      "type": "integer",
      "default": 4000,
      "description": "Reserved — not used in v0.4. Retained for forward compat."
    },
    "prompt-squeeze.interactive": {
      "type": "boolean",
      "default": false,
      "deprecated": true,
      "description": "Folded into mode='interactive' in v0.4. Ignored."
    },
    "prompt-squeeze.explain": {
      "type": "string",
      "enum": ["off", "on"],
      "default": "off",
      "description": "When 'on', the hook stores per-squeeze explain artifacts at ~/.claude/prompt-squeeze/explain/. Required for /sq explain and /sq undo."
    },
    "prompt-squeeze.telemetry": {
      "type": "string",
      "enum": ["off", "local", "team"],
      "default": "local"
    },
    "prompt-squeeze.model_override": { "type": ["string", "null"], "default": null },
    "prompt-squeeze.team_endpoint": { "type": ["string", "null"], "default": null }
  }
}
```

- [ ] **Step 2: Run tests**

Run: `cd ~/projects/prompt-squeeze && uv run pytest tests/ 2>&1 | tail -2`
Expected: all pass. If `test_data_files.py` validates schema fields, update those expectations.

- [ ] **Step 3: Commit**

```bash
git add settings.schema.json
git commit -m "v0.4 settings schema: add mode='interactive', block_threshold=500, explain opt-in"
```

---

## Task 7: README — document v0.4 behavior + escape hatches

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update the Settings table and add a Migration section**

Edit `README.md`. Replace the Settings table and the Platform constraint paragraph with:

```markdown
## Settings (v0.4)

See [`settings.schema.json`](./settings.schema.json) for the full schema. Keys live under `.claude/settings.json` in your project (or your user-level settings).

| Key | Default | Notes |
| --- | --- | --- |
| `prompt-squeeze.mode` | `interactive` | `off` disables; `advise` is v0.3 behavior (nudge only); `interactive` blocks long prompts and offers `/sq y` (v0.4 default). |
| `prompt-squeeze.block_threshold` | `500` | v0.4: prompts above this token count are blocked. |
| `prompt-squeeze.explain` | `off` | When `on`, per-squeeze artifacts are stored locally for `/sq explain` and `/sq undo`. Opt-in. |
| `prompt-squeeze.notify_threshold` | `0.25` | Min compressible fraction to nudge in advise mode. |
| `prompt-squeeze.telemetry` | `local` | `local`, `team`, or `off`. |

## v0.4 default flow

1. You type a prompt > 500 tokens.
2. The hook blocks submission and shows a side-by-side diff with savings: `prompt-squeeze: 1,248 tokens. Compressed saves 487 tokens (~$0.0009, 0.31 Wh).`
3. Reply with `/sq y` (send squeezed once), `/sq y session` (send squeezed AND auto-confirm rest of session), or `/sq n` (send original).
4. After `/sq y session`, subsequent long prompts auto-block with a terse one-liner; `/sq y` confirms in one keystroke.
5. Escape hatches: `/sq off` disables for the rest of the session; `/sq undo` resends the last prompt as original (requires `explain: on`).

## Migration from v0.3

If you were using v0.3 advise mode and prefer it:

```json
{ "prompt-squeeze.mode": "advise" }
```

The v0.3 nudge behavior is preserved exactly — the hook will continue to emit `additionalContext` recommending `/squeeze` instead of blocking.
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "Document v0.4 default flow + migration from v0.3 advise mode"
```

---

## Task 8: Integration smoke test

End-to-end: hook receives a long prompt, blocks, writes pending; `/sq y` semantics resolve correctly.

**Files:**
- Create: `tests/integration/test_block_recovery_flow.py`

- [ ] **Step 1: Write the integration test**

Create `tests/integration/test_block_recovery_flow.py`:

```python
# ABOUTME: End-to-end smoke test for the v0.4 block-and-recover flow.
# ABOUTME: Verifies hook block writes a usable pending entry and the /sq y semantics resolve correctly.

import hashlib
import json


def test_long_prompt_blocks_and_pending_resolves_to_squeezed_text(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    import sys
    from pathlib import Path
    repo = Path(__file__).resolve().parents[2]
    for sub in ("hooks", repo / "skills" / "prompt-squeeze" / "scripts"):
        if str(sub) not in sys.path:
            sys.path.insert(0, str(sub))

    import pending_cache
    from user_prompt_submit import _process

    sid = "integration_test_session"
    sh = hashlib.sha256(sid.encode()).hexdigest()[:16]

    long_prompt = "Please could you help me " + "explain async/await in Python " * 80
    payload = {
        "session_id": sid,
        "cwd": str(tmp_path),
        "prompt": long_prompt,
    }

    result = _process(payload)
    out = result["output"]

    # Hook blocked
    assert out.get("decision") == "block"
    reason = out["reason"]
    assert "/sq y" in reason

    # Pending cache has an entry
    entry = pending_cache.read_pending(sh)
    assert entry is not None
    assert entry["consumed"] is False
    assert "squeezed_text" in entry

    # The squeezed text is what /sq y would emit
    squeezed = entry["squeezed_text"]
    assert len(squeezed) > 0
    assert len(squeezed) < len(long_prompt)
    # And it preserves the topic
    assert "async/await" in squeezed
```

- [ ] **Step 2: Run, expect pass**

Run: `cd ~/projects/prompt-squeeze && uv run pytest tests/integration/test_block_recovery_flow.py -v 2>&1 | tail -10`
Expected: 1 PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_block_recovery_flow.py
git commit -m "Add integration smoke test for v0.4 block-and-recover flow"
```

---

## Self-review

**Spec coverage** (Components 2 + 3 of [the design spec](docs/superpowers/specs/2026-05-04-prompt-squeeze-v04-design.md)):
- Hook flips to interactive default ✓ (Task 4)
- Consent state machine (null / yes-session / no) ✓ (Tasks 1, 4)
- Pending cache + recovery ✓ (Tasks 2, 5)
- Per-prompt visibility one-liner ✓ (Task 4 — terse banner is the visibility)
- Migration documentation ✓ (Task 7)

**Placeholder scan:** All steps include actual code. No "TODO", "TBD", or "implement later." ✓

**Type consistency:** `read_consent` / `write_consent` (3 valid states), `read_pending` / `write_pending` (param list matches across tasks), `mark_consumed`. `_process()` returns `{"output": {...}, "log": {...}}` consistently. ✓

## Execution handoff

Same as Plan A: inline execution under skip-permissions, commit after each task, surface issues at boundaries.
