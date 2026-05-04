# ABOUTME: Eval harness for prompt-squeeze - reports compression ratio + must_preserve fidelity per row,
# ABOUTME: optional Claude-as-judge fidelity scoring (paid, gated by --judge), CI-style threshold gates.

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from pathlib import Path

_THIS = Path(__file__).resolve()
# scripts/eval/run_eval.py -> scripts/ on parent[1], skill root on parent[2]
_SCRIPTS_DIR = _THIS.parent.parent
_SKILL_DIR = _SCRIPTS_DIR.parent
_EVAL_PATH = _SKILL_DIR / "data" / "eval_set.jsonl"

# Make sibling scripts importable regardless of how this is invoked.
sys.path.insert(0, str(_SCRIPTS_DIR))

from compress import compress, compression_ratio  # noqa: E402
from estimate import estimate  # noqa: E402

# Seed-set thresholds: looser than the production CI gate from PRD section 10.
# PRD target is median rubric >= 0.95 with none below 0.85, but with only 20
# seed prompts we use these heuristic-only floors and document the gap here.
_MIN_MEDIAN_COMPRESSION = 0.10
_MIN_MEDIAN_FIDELITY = 0.85


_JUDGE_SYSTEM = (
    "You are a strict prompt-fidelity grader. Given an ORIGINAL prompt and a "
    "COMPRESSED prompt, return a single JSON object: "
    '{"fidelity": <float 0..1>, "reason": "<one short sentence>"} . '
    "1.0 means the compressed version preserves all task-relevant intent, "
    "constraints, identifiers, and code references. Drop scores hard for any "
    "loss of file paths, error strings, version numbers, or task verbs."
)


def _load_eval(path: Path) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def _check_must_preserve(compressed: str, must_preserve: list[str]) -> tuple[int, list[str]]:
    missing = [s for s in must_preserve if s not in compressed]
    return len(must_preserve) - len(missing), missing


def _judge_user_message(original: str, compressed: str) -> str:
    return (
        "ORIGINAL:\n"
        f"{original}\n\n"
        "COMPRESSED:\n"
        f"{compressed}\n\n"
        "Return only the JSON object."
    )


def _parse_judge_response(raw: str) -> tuple[float, str]:
    raw = raw.strip()
    # Strip markdown fences if the model wrapped JSON in ```json ... ```
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:].strip()
    try:
        parsed = json.loads(raw)
        return float(parsed["fidelity"]), str(parsed.get("reason", ""))
    except Exception:
        return 0.0, f"unparseable judge response: {raw[:80]!r}"


def _judge_with_sdk(original: str, compressed: str, model: str) -> tuple[float, str]:
    from anthropic import Anthropic

    client = Anthropic()
    resp = client.messages.create(
        model=model,
        max_tokens=200,
        system=_JUDGE_SYSTEM,
        messages=[{"role": "user", "content": _judge_user_message(original, compressed)}],
    )
    raw = "".join(block.text for block in resp.content if getattr(block, "type", "") == "text")
    return _parse_judge_response(raw)


def _judge_with_cli(original: str, compressed: str, model: str) -> tuple[float, str]:
    """Use `claude -p` subprocess. Slower per call and pays the system-prompt cache-creation
    cost on every invocation, but works with the user's existing Claude Code auth."""
    import subprocess

    full_prompt = _JUDGE_SYSTEM + "\n\n" + _judge_user_message(original, compressed)
    try:
        result = subprocess.run(
            ["claude", "-p", "--model", model, "--output-format", "json", full_prompt],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return 0.0, f"claude -p failed: {type(e).__name__}"

    if result.returncode != 0:
        return 0.0, f"claude -p exit {result.returncode}: {result.stderr[:80]}"
    try:
        envelope = json.loads(result.stdout)
        text = envelope.get("result", "") if isinstance(envelope, dict) else ""
    except json.JSONDecodeError:
        text = result.stdout
    return _parse_judge_response(text)


def _judge(original: str, compressed: str, *, backend: str, model: str) -> tuple[float, str]:
    if backend == "auto":
        backend = "sdk" if os.environ.get("ANTHROPIC_API_KEY") else "cli"
    if backend == "sdk":
        return _judge_with_sdk(original, compressed, model)
    if backend == "cli":
        return _judge_with_cli(original, compressed, model)
    raise ValueError(f"unknown judge backend: {backend}")


def _stratified_sample(rows: list[dict], sample_size: int) -> list[dict]:
    """Take an even number of rows from each family. Deterministic by id sort order."""
    import collections

    by_family: dict[str, list[dict]] = collections.defaultdict(list)
    for r in rows:
        by_family[r.get("family", "unknown")].append(r)
    families = sorted(by_family.keys())
    if not families:
        return rows[:sample_size]
    per_family = max(1, sample_size // len(families))
    out: list[dict] = []
    for fam in families:
        family_rows = sorted(by_family[fam], key=lambda r: r["id"])
        out.extend(family_rows[:per_family])
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the prompt-squeeze eval harness.")
    parser.add_argument("--judge", action="store_true", help="Enable Claude-as-judge fidelity scoring (paid).")
    parser.add_argument(
        "--judge-backend",
        choices=["auto", "sdk", "cli"],
        default="auto",
        help="auto: SDK if ANTHROPIC_API_KEY set, else claude -p CLI. sdk requires API key. cli uses subscription auth.",
    )
    parser.add_argument(
        "--judge-sample",
        type=int,
        default=0,
        help="Run --judge on only N rows (stratified across families). 0 = all rows.",
    )
    parser.add_argument(
        "--judge-model",
        default="claude-sonnet-4-6",
        help="Model to use for judge calls. Sonnet is the cheapest reasonable judge.",
    )
    parser.add_argument("--model", default="claude-sonnet-4-6", help="Pricing model for savings estimate.")
    parser.add_argument("--eval-path", default=str(_EVAL_PATH))
    args = parser.parse_args(argv)

    rows = _load_eval(Path(args.eval_path))
    if not rows:
        print("no eval rows loaded", file=sys.stderr)
        return 2

    judge_target_ids: set[str] = set()
    if args.judge:
        if args.judge_sample > 0:
            sample = _stratified_sample(rows, args.judge_sample)
            judge_target_ids = {r["id"] for r in sample}
            print(
                f"# judge: sampling {len(judge_target_ids)} of {len(rows)} rows "
                f"(stratified by family) backend={args.judge_backend} model={args.judge_model}"
            )
        else:
            judge_target_ids = {r["id"] for r in rows}
            print(
                f"# judge: all {len(rows)} rows backend={args.judge_backend} model={args.judge_model}"
            )

    ratios: list[float] = []
    fidelities: list[float] = []
    must_preserve_failures = 0

    for row in rows:
        original = row["prompt"]
        compressed = compress(original)
        ratio = compression_ratio(original, compressed)
        ratios.append(ratio)

        kept, missing = _check_must_preserve(compressed, row.get("must_preserve", []))
        if missing:
            must_preserve_failures += 1

        # Cheap savings preview using cl100k token counts.
        try:
            import tiktoken
            enc = tiktoken.get_encoding("cl100k_base")
            o_tok = len(enc.encode(original))
            c_tok = len(enc.encode(compressed))
        except Exception:
            o_tok = len(original.split())
            c_tok = len(compressed.split())

        savings = estimate(o_tok, c_tok, args.model)

        line = (
            f"{row['id']:<26} family={row['family']:<18} "
            f"ratio={ratio:.3f} kept={kept}/{len(row.get('must_preserve', []))} "
            f"saved=${savings['saved_dollars']:.4f}"
        )
        if missing:
            line += f" MISSING={missing}"
        print(line)

        if args.judge and row["id"] in judge_target_ids:
            fidelity, reason = _judge(
                original,
                compressed,
                backend=args.judge_backend,
                model=args.judge_model,
            )
            fidelities.append(fidelity)
            print(f"  judge: fidelity={fidelity:.2f} reason={reason}")

    median_ratio = statistics.median(ratios)
    pct_above_25 = sum(1 for r in ratios if r >= 0.25) / len(ratios)

    print()
    print(f"rows: {len(rows)}")
    print(f"median compression ratio: {median_ratio:.3f}")
    print(f"% of prompts >= 25% compression: {pct_above_25:.1%}")
    print(f"must_preserve failures: {must_preserve_failures}/{len(rows)}")
    if fidelities:
        median_fidelity = statistics.median(fidelities)
        print(f"median judge fidelity: {median_fidelity:.3f}")
    else:
        median_fidelity = None

    exit_code = 0
    if median_ratio < _MIN_MEDIAN_COMPRESSION:
        print(
            f"FAIL: median compression {median_ratio:.3f} < {_MIN_MEDIAN_COMPRESSION:.2f}",
            file=sys.stderr,
        )
        exit_code = 1
    if must_preserve_failures > 0:
        print(
            f"FAIL: {must_preserve_failures} rows dropped a must_preserve substring",
            file=sys.stderr,
        )
        exit_code = 1
    if median_fidelity is not None and median_fidelity < _MIN_MEDIAN_FIDELITY:
        print(
            f"FAIL: median fidelity {median_fidelity:.3f} < {_MIN_MEDIAN_FIDELITY:.2f}",
            file=sys.stderr,
        )
        exit_code = 1

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
