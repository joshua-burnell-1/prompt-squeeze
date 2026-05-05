#!/usr/bin/env python3
# ABOUTME: UserPromptSubmit hook for prompt-squeeze. Measures prompts, runs Stage 1 compression
# ABOUTME: via the bundled skill, and emits an additionalContext nudge when meaningful savings exist.

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone  # noqa: UP017 — keeping 3.9 compat for hook
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SKILL_SCRIPTS = PLUGIN_ROOT / "skills" / "prompt-squeeze" / "scripts"
HOOKS_DIR = Path(__file__).resolve().parent
PRICING_PATH = PLUGIN_ROOT / "skills" / "prompt-squeeze" / "data" / "pricing.json"
LOG_DIR = Path.home() / ".claude" / "prompt-squeeze"
LOG_PATH = LOG_DIR / "log.jsonl"

# Make sibling helper modules importable when the hook runs as a script.
if str(HOOKS_DIR) not in sys.path:
    sys.path.insert(0, str(HOOKS_DIR))

import explain_artifact  # noqa: E402
import pending_cache  # noqa: E402
import session_state  # noqa: E402

DEFAULT_SETTINGS = {
    # v0.4: default flips to "interactive" — block long prompts and offer /sq y for realized savings.
    # Set to "advise" for v0.3 nudge-only behavior, "off" to disable the hook.
    "mode": "interactive",
    # v0.4: prompts above this token count are blocked in interactive mode.
    "block_threshold": 500,
    # Legacy v0.3 advise-mode threshold. Honored when mode == "advise".
    "warn_threshold": 800,
    "notify_threshold": 0.25,
    "hard_limit": 4000,
    "interactive": False,  # legacy, ignored when mode == "interactive"
    "telemetry": "local",
    "model_override": None,
    "team_endpoint": None,
    # v0.4: per-squeeze artifact opt-in (Plan C). When "on", the hook stores
    # original_text in pending_cache so /sq undo can resend the original.
    "explain": "off",
}

WALL_BUDGET_MS = 2500


def _short_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _load_settings(cwd: str | None) -> dict:
    settings = dict(DEFAULT_SETTINGS)
    candidates = []
    if cwd:
        candidates.append(Path(cwd) / ".claude" / "settings.json")
    candidates.append(Path.home() / ".claude" / "settings.json")
    for path in candidates:
        try:
            if path.is_file():
                raw = json.loads(path.read_text())
                for key in list(DEFAULT_SETTINGS.keys()):
                    full = f"prompt-squeeze.{key}"
                    if full in raw:
                        settings[key] = raw[full]
        except Exception:
            continue
    return settings


def _load_pricing(model: str) -> dict:
    try:
        data = json.loads(PRICING_PATH.read_text())
        if model in data and isinstance(data[model], dict):
            return data[model]
    except Exception:
        pass
    return {"input_per_mtok": 3.00, "output_per_mtok": 15.00}


def _resolve_model(settings: dict) -> str:
    override = settings.get("model_override")
    if override:
        return override
    env_model = os.environ.get("CLAUDE_MODEL")
    if env_model:
        return env_model
    return "claude-sonnet-4-6"


def _tokenize(text: str) -> int:
    """Token count via tiktoken cl100k_base when available; word-count*1.3 fallback otherwise.
    Anthropic's tokenizer differs from cl100k, but cl100k is the closest public approximation
    and is the same encoding used by the skill's compress/estimate scripts."""
    try:
        import tiktoken  # type: ignore
        return len(tiktoken.get_encoding("cl100k_base").encode(text))
    except ImportError:
        # ~1.3 tokens per word is a safe upper-bound approximation for English prose.
        return max(1, int(len(text.split()) * 1.3))


def _import_skill():
    if str(SKILL_SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SKILL_SCRIPTS))
    compress_mod = None
    estimate_mod = None
    try:
        import compress as compress_mod  # type: ignore
    except Exception:
        compress_mod = None
    try:
        import estimate as estimate_mod  # type: ignore
    except Exception:
        estimate_mod = None
    return compress_mod, estimate_mod


def _fallback_compress(text: str) -> str:
    lines = []
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        lines.append(" ".join(stripped.split()))
    return "\n".join(lines)


def _fallback_estimate(original_tokens: int, compressed_tokens: int, model: str) -> dict:
    saved = max(0, original_tokens - compressed_tokens)
    pricing = _load_pricing(model)
    inflation = pricing.get("tokenizer_inflation", 1.0)
    effective_saved = saved * inflation
    dollars = (effective_saved / 1_000_000.0) * pricing.get("input_per_mtok", 3.00)
    wh = (effective_saved * 0.39) / 3600.0
    return {
        "saved_input_tokens": saved,
        "saved_dollars": round(dollars, 6),
        "saved_wh": round(wh, 4),
    }


def _read_prompt(payload: dict) -> str:
    if isinstance(payload.get("prompt"), str):
        return payload["prompt"]
    tool_input = payload.get("tool_input") or {}
    if isinstance(tool_input, dict) and isinstance(tool_input.get("prompt"), str):
        return tool_input["prompt"]
    return ""


def _write_log(row: dict, telemetry: str) -> None:
    if telemetry == "off":
        return
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, separators=(",", ":")) + "\n")
    except Exception:
        return


def _wrap(text: str, width: int) -> list[str]:
    """Word-wrap to width chars; preserves explicit newlines. Empty input → [""]."""
    if not text:
        return [""]
    out: list[str] = []
    for paragraph in text.splitlines() or [""]:
        if not paragraph:
            out.append("")
            continue
        line = ""
        for word in paragraph.split(" "):
            if line and len(line) + 1 + len(word) > width:
                out.append(line)
                line = word
            else:
                line = (line + " " + word) if line else word
            # Hard-break absurdly long single words
            while len(line) > width:
                out.append(line[:width])
                line = line[width:]
        if line:
            out.append(line)
    return out


def _side_by_side(
    original: str,
    compressed: str,
    *,
    width: int = 38,
    max_lines: int = 18,
    original_label: str = "ORIGINAL",
    compressed_label: str = "COMPRESSED",
) -> str:
    """Render two prompts as a 2-column ASCII layout. Truncates long prompts to max_lines per side."""
    left = _wrap(original, width)
    right = _wrap(compressed, width)

    truncated = False
    if len(left) > max_lines:
        left = left[: max_lines - 1] + [f"... ({len(left) - max_lines + 1} more lines)"]
        truncated = True
    if len(right) > max_lines:
        right = right[: max_lines - 1] + [f"... ({len(right) - max_lines + 1} more lines)"]
        truncated = True

    rows = max(len(left), len(right))
    left += [""] * (rows - len(left))
    right += [""] * (rows - len(right))

    sep = "-" * width + "-+-" + "-" * width
    lines = [
        f"{original_label:<{width}} | {compressed_label}",
        sep,
    ]
    for l_, r_ in zip(left, right):
        lines.append(f"{l_:<{width}} | {r_}")
    if truncated:
        lines.append("(prompts truncated for display; receipt below uses full token counts)")
    return "\n".join(lines)


def _nudge_message(original: int, saved: int, dollars: float, wh: float) -> str:
    return (
        f"User's prompt is {original} tokens; an estimated {saved} tokens "
        f"(~${dollars:.4f}, ~{wh:.2f} Wh) could be saved by running `/squeeze`. "
        "Respond efficiently and, if a future similar prompt would benefit, "
        "mention the available `/squeeze` command in your final paragraph."
    )


def _next_seq(session_hash: str) -> int:
    """Next sequence number for this session, derived from any existing pending entry."""
    try:
        existing = pending_cache.read_pending(session_hash)
        if existing:
            return int(existing.get("seq", 0)) + 1
    except Exception:
        pass
    return 1


def _process(payload: dict) -> dict:
    started = time.monotonic()
    settings = _load_settings(payload.get("cwd"))

    mode = settings.get("mode", "interactive")
    if mode == "off":
        return {"output": {}, "log": None}

    prompt = _read_prompt(payload)
    if not prompt:
        return {"output": {}, "log": None}

    session_raw = str(payload.get("session_id") or "anon")
    session_hash = _short_hash(session_raw)
    prompt_hash = _short_hash(prompt)
    model = _resolve_model(settings)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    original_tokens = _tokenize(prompt)

    consent = session_state.read_consent(session_hash)

    base_log = {
        "ts": now,
        "session": session_hash,
        "model": model,
        "prompt_hash": prompt_hash,
        "original_tokens": original_tokens,
        "achievable_tokens": 0,
        "achievable_pct": 0.0,
        "estimated_dollars_saved": 0.0,
        "estimated_wh_saved": 0.0,
        "action": "measure_only",
        "user_action": None,
        "consent": consent,
        "mode": mode,
    }

    # User opted out for this session — pass through unchanged, log measurement only.
    if consent == "no":
        base_log["action"] = "consent_no"
        return {"output": {}, "log": base_log}

    # Threshold gate. interactive mode uses block_threshold; advise mode keeps warn_threshold.
    threshold = settings.get(
        "block_threshold" if mode == "interactive" else "warn_threshold",
        500 if mode == "interactive" else 800,
    )
    if original_tokens < threshold:
        return {"output": {}, "log": base_log}

    if (time.monotonic() - started) * 1000 > WALL_BUDGET_MS:
        base_log["action"] = "hook_timeout"
        return {"output": {}, "log": base_log}

    # Compress. Use compress_with_hits when available so /sq explain has rule attribution.
    compress_mod, estimate_mod = _import_skill()
    rule_hits: list = []
    if compress_mod and hasattr(compress_mod, "compress_with_hits"):
        try:
            compressed_text, rule_hits = compress_mod.compress_with_hits(prompt)
        except Exception:
            compressed_text = _fallback_compress(prompt)
    elif compress_mod and hasattr(compress_mod, "compress"):
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

    # ----- advise mode: legacy v0.3 nudge behavior -----
    if mode == "advise":
        if achievable_pct < settings.get("notify_threshold", 0.25):
            base_log["action"] = "silent"
            return {"output": {}, "log": base_log}

        if (time.monotonic() - started) * 1000 > WALL_BUDGET_MS:
            base_log["action"] = "hook_timeout"
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

    # ----- interactive mode (v0.4 default): block + write pending cache -----
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

    # When explain is opted in, persist a per-squeeze artifact for /sq explain.
    if explain_on:
        wrote = explain_artifact.write_artifact(
            session_hash=session_hash,
            seq=seq,
            original_text=prompt,
            squeezed_text=compressed_text,
            tokens_original=original_tokens,
            tokens_squeezed=compressed_tokens,
            rules_fired=rule_hits,
        )
        base_log["explain_artifact_written"] = bool(wrote)

    if (time.monotonic() - started) * 1000 > WALL_BUDGET_MS:
        base_log["action"] = "hook_timeout"
        return {"output": {}, "log": base_log}

    if consent == "yes-session":
        base_log["action"] = "block_terse"
        reason = (
            f"prompt-squeeze auto: {original_tokens} -> {compressed_tokens} tok "
            f"(-{achievable_pct:.0%}) saved ~${dollars:.4f}, ~{wh:.2f} Wh\n"
            "Reply: /sq y to send the squeezed version, /sq n to send original, /sq off to disable for this session"
        )
    else:
        # No consent yet — full banner with side-by-side diff + three-choice prompt.
        base_log["action"] = "block_full_banner"
        diff = _side_by_side(
            prompt,
            compressed_text,
            original_label=f"ORIGINAL ({original_tokens} tok)",
            compressed_label=f"COMPRESSED ({compressed_tokens} tok, -{achievable_pct:.0%})",
        )
        reason = (
            f"prompt-squeeze: your prompt is {original_tokens} tokens. A compressed "
            f"version saves {saved_tokens} tokens (~${dollars:.4f}, ~{wh:.2f} Wh).\n\n"
            f"{diff}\n\n"
            "Reply with one of:\n"
            "  /sq y          send the squeezed version once\n"
            "  /sq y session  send squeezed AND auto-confirm for the rest of this session\n"
            "  /sq n          send your original prompt unchanged\n"
            "  /sq off        disable prompt-squeeze for the rest of this session"
        )

    return {
        "output": {"decision": "block", "reason": reason},
        "log": base_log,
    }


def main() -> int:
    if "--self-test" in sys.argv:
        return _self_test()

    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
    except Exception as exc:
        _write_log(
            {
                "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "session": "anon",
                "model": "unknown",
                "prompt_hash": "",
                "original_tokens": 0,
                "achievable_tokens": 0,
                "achievable_pct": 0.0,
                "estimated_dollars_saved": 0.0,
                "estimated_wh_saved": 0.0,
                "action": "hook_error",
                "user_action": None,
                "error_class": type(exc).__name__,
            },
            "local",
        )
        sys.stdout.write("")
        return 0

    try:
        result = _process(payload)
        out = result.get("output") or {}
        log_row = result.get("log")
        if log_row is not None:
            settings = _load_settings(payload.get("cwd"))
            _write_log(log_row, settings.get("telemetry", "local"))
        if out:
            sys.stdout.write(json.dumps(out))
        return 0
    except Exception as exc:
        _write_log(
            {
                "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "session": _short_hash(str(payload.get("session_id") or "anon")),
                "model": "unknown",
                "prompt_hash": "",
                "original_tokens": 0,
                "achievable_tokens": 0,
                "achievable_pct": 0.0,
                "estimated_dollars_saved": 0.0,
                "estimated_wh_saved": 0.0,
                "action": "hook_error",
                "user_action": None,
                "error_class": type(exc).__name__,
            },
            "local",
        )
        return 0


def _run_once(payload: dict) -> tuple[int, str]:
    import io

    buf = io.StringIO()
    old_stdin, old_stdout = sys.stdin, sys.stdout
    saved_argv = list(sys.argv)
    sys.argv = [sys.argv[0]]
    sys.stdin = io.StringIO(json.dumps(payload))
    sys.stdout = buf
    try:
        rc = main()
    finally:
        sys.stdin, sys.stdout = old_stdin, old_stdout
        sys.argv = saved_argv
    return rc, buf.getvalue()


def _run_raw(raw: str) -> tuple[int, str]:
    import io

    buf = io.StringIO()
    old_stdin, old_stdout = sys.stdin, sys.stdout
    saved_argv = list(sys.argv)
    sys.argv = [sys.argv[0]]
    sys.stdin = io.StringIO(raw)
    sys.stdout = buf
    try:
        rc = main()
    finally:
        sys.stdin, sys.stdout = old_stdin, old_stdout
        sys.argv = saved_argv
    return rc, buf.getvalue()


def _self_test() -> int:
    import tempfile
    import types

    tmp_home = tempfile.mkdtemp(prefix="ps-selftest-")
    os.environ["HOME"] = tmp_home
    global LOG_DIR, LOG_PATH
    LOG_DIR = Path(tmp_home) / ".claude" / "prompt-squeeze"
    LOG_PATH = LOG_DIR / "log.jsonl"

    if "compress" not in sys.modules:
        stub_compress = types.ModuleType("compress")
        def _stub_compress(text: str) -> str:
            kept = []
            words = text.split()
            for i, w in enumerate(words):
                lw = w.lower().strip(".,;:")
                if lw in {"please", "kindly", "very", "really", "just",
                          "actually", "basically", "thoroughly", "overly",
                          "great", "make", "sure"}:
                    continue
                if i % 3 == 0:
                    continue
                kept.append(w)
            return " ".join(kept)
        stub_compress.compress = _stub_compress  # type: ignore[attr-defined]
        sys.modules["compress"] = stub_compress
    if "estimate" not in sys.modules:
        stub_estimate = types.ModuleType("estimate")
        def _stub_estimate(*, original_tokens: int, compressed_tokens: int, model: str) -> dict:
            saved = max(0, original_tokens - compressed_tokens)
            return {
                "saved_input_tokens": saved,
                "saved_dollars": round(saved * 3e-6, 6),
                "saved_wh": round(saved * 0.39 / 3600.0, 4),
            }
        stub_estimate.estimate = _stub_estimate  # type: ignore[attr-defined]
        sys.modules["estimate"] = stub_estimate

    results: list[tuple[str, bool, str]] = []

    def run_case(name: str, payload: dict, predicate) -> None:
        rc, out = _run_once(payload)
        ok, detail = predicate(rc, out)
        results.append((name, ok, detail or out[:200]))

    short_payload = {
        "session_id": "s1",
        "cwd": tmp_home,
        "prompt": "hi",
    }
    run_case(
        "short_prompt_silent",
        short_payload,
        lambda rc, out: (rc == 0 and out == "", f"rc={rc} out={out!r}"),
    )

    long_text = (
        "Please could you kindly help me to write a function that, "
        "in a very verbose and overly polite manner, takes a list of "
        "integers and returns the sum, but only of the even numbers, "
        "and please make sure to include comments explaining each step "
        "in great detail because I want to understand it thoroughly. "
    ) * 40
    long_payload = {
        "session_id": "s2",
        "cwd": tmp_home,
        "prompt": long_text,
    }
    # v0.4 default — interactive mode blocks long prompts with /sq y prompt.
    run_case(
        "long_prompt_block_default",
        long_payload,
        lambda rc, out: (
            rc == 0 and '"decision":"block"' in out.replace(" ", "") and "/sq y" in out,
            f"rc={rc} out_len={len(out)} has_block={'block' in out}",
        ),
    )

    # v0.3 advise-mode behavior (opt-in via settings) still works — emits nudge.
    settings_dir = Path(tmp_home) / ".claude"
    settings_dir.mkdir(parents=True, exist_ok=True)
    (settings_dir / "settings.json").write_text(json.dumps({
        "prompt-squeeze.mode": "advise",
    }))
    run_case(
        "long_prompt_nudge_advise",
        long_payload,
        lambda rc, out: (
            rc == 0 and "additionalContext" in out and "/squeeze" in out,
            f"rc={rc} out_len={len(out)} has_ctx={'additionalContext' in out}",
        ),
    )
    (settings_dir / "settings.json").unlink()

    hard_payload = {
        "session_id": "s3",
        "cwd": tmp_home,
        "prompt": long_text * 10,
    }
    # interactive mode blocks long prompts by default — no settings needed.
    run_case(
        "hard_limit_block",
        hard_payload,
        lambda rc, out: (
            rc == 0 and '"decision":"block"' in out.replace(" ", ""),
            f"rc={rc} out_head={out[:160]!r}",
        ),
    )

    rc, bad_out = _run_raw("{not json")
    results.append((
        "error_path_safe",
        rc == 0 and bad_out == "",
        f"rc={rc} out={bad_out!r}",
    ))

    log_text = LOG_PATH.read_text() if LOG_PATH.exists() else ""
    no_raw = ("Please could you kindly" not in log_text) and ("hi" not in (
        " ".join(line for line in log_text.splitlines() if '"prompt"' in line)
    ))
    results.append(("log_has_no_raw_prompt", no_raw, f"log_bytes={len(log_text)}"))

    failed = [r for r in results if not r[1]]
    for name, ok, detail in results:
        status = "PASS" if ok else "FAIL"
        sys.stderr.write(f"[{status}] {name}: {detail}\n")

    if failed:
        sys.stderr.write(f"\n{len(failed)} failure(s)\n")
        return 1

    sample = {}
    for name, payload in [("short", short_payload), ("long", long_payload)]:
        _, sample[name] = _run_once(payload)

    settings_dir.mkdir(parents=True, exist_ok=True)
    (settings_dir / "settings.json").write_text(json.dumps({
        "prompt-squeeze.interactive": True,
        "prompt-squeeze.hard_limit": 500,
    }))
    _, sample["hard"] = _run_once(hard_payload)
    (settings_dir / "settings.json").unlink()

    sys.stderr.write("\nSample stdout:\n")
    sys.stderr.write(f"  short -> {sample['short']!r}\n")
    sys.stderr.write(f"  long  -> {sample['long'][:240]!r}\n")
    sys.stderr.write(f"  hard  -> {sample['hard'][:240]!r}\n")
    sys.stderr.write("ALL PASS\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
