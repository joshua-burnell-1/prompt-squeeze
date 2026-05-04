# ABOUTME: Cost + energy estimator for prompt-squeeze. Reads pricing.json and energy.json siblings,
# ABOUTME: emits JSON or markdown receipts; exposes estimate() for tests/eval harness.

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_DATA_DIR = _SCRIPT_DIR.parent / "data"
_TEMPLATE_PATH = _SCRIPT_DIR.parent / "templates" / "receipt.md"

_PRICING_PATH = _DATA_DIR / "pricing.json"
_ENERGY_PATH = _DATA_DIR / "energy.json"


def _load_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _round(value: float, places: int = 4) -> float:
    return round(float(value), places)


def estimate(
    original_tokens: int,
    compressed_tokens: int,
    model: str,
    expected_output_multiplier: float = 0.5,
) -> dict:
    if original_tokens < 0 or compressed_tokens < 0:
        raise ValueError("token counts must be non-negative")
    if compressed_tokens > original_tokens:
        raise ValueError("compressed_tokens cannot exceed original_tokens")
    if expected_output_multiplier < 0:
        raise ValueError("expected_output_multiplier must be non-negative")

    pricing = _load_json(_PRICING_PATH)
    energy = _load_json(_ENERGY_PATH)

    if model not in pricing or not isinstance(pricing[model], dict):
        raise KeyError(f"model '{model}' not found in pricing.json")

    model_pricing = pricing[model]
    input_per_mtok = float(model_pricing["input_per_mtok"])
    output_per_mtok = float(model_pricing["output_per_mtok"])
    inflation = model_pricing.get("tokenizer_inflation")

    saved_input = original_tokens - compressed_tokens
    saved_output_estimate = int(round(saved_input * expected_output_multiplier))

    if inflation:
        billed_input = saved_input * float(inflation)
        billed_output = saved_output_estimate * float(inflation)
    else:
        billed_input = saved_input
        billed_output = saved_output_estimate

    saved_dollars = (
        (billed_input / 1_000_000) * input_per_mtok
        + (billed_output / 1_000_000) * output_per_mtok
    )

    total_saved_tokens = saved_input + saved_output_estimate
    joules_per_token = float(energy["default_joules_per_token"])
    grid_kg_co2_per_kwh = float(energy["grid_kg_co2_per_kwh"])

    saved_joules = total_saved_tokens * joules_per_token
    saved_wh = saved_joules / 3600.0
    saved_kwh = saved_wh / 1000.0
    saved_g_co2e = saved_kwh * grid_kg_co2_per_kwh * 1000.0

    ratio = (saved_input / original_tokens) if original_tokens > 0 else 0.0

    return {
        "model": model,
        "original_tokens": int(original_tokens),
        "compressed_tokens": int(compressed_tokens),
        "saved_input_tokens": int(saved_input),
        "saved_output_estimate": int(saved_output_estimate),
        "saved_total_tokens": int(total_saved_tokens),
        "saved_dollars": _round(saved_dollars, 4),
        "saved_wh": _round(saved_wh, 4),
        "saved_g_co2e": _round(saved_g_co2e, 4),
        "compression_ratio": _round(ratio, 4),
        "tokenizer_inflation_applied": float(inflation) if inflation else None,
        "sources": {
            "pricing": pricing.get("_source", ""),
            "energy": energy.get("source", ""),
            "grid": energy.get("grid_source", ""),
        },
    }


def render_markdown(receipt: dict) -> str:
    template = _TEMPLATE_PATH.read_text(encoding="utf-8")
    inflation = receipt["tokenizer_inflation_applied"]
    if inflation:
        footer = (
            f"Note: tokenizer_inflation x{inflation} applied for {receipt['model']} "
            "(Anthropic tokenizer differs from cl100k baseline)."
        )
    else:
        footer = ""

    pct = f"{receipt['compression_ratio'] * 100:.1f}%"
    return template.format(
        original_tokens=receipt["original_tokens"],
        compressed_tokens=receipt["compressed_tokens"],
        compression_pct=pct,
        model=receipt["model"],
        saved_input_tokens=receipt["saved_input_tokens"],
        saved_output_estimate=receipt["saved_output_estimate"],
        saved_total_tokens=receipt["saved_total_tokens"],
        saved_dollars=f"{receipt['saved_dollars']:.4f}",
        saved_wh=f"{receipt['saved_wh']:.4f}",
        saved_g_co2e=f"{receipt['saved_g_co2e']:.4f}",
        energy_source=receipt["sources"]["energy"],
        pricing_source=receipt["sources"]["pricing"],
        tokenizer_inflation_footer=footer,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Estimate dollar + energy savings from prompt compression.")
    parser.add_argument("--original-tokens", type=int, required=True)
    parser.add_argument("--compressed-tokens", type=int, required=True)
    parser.add_argument("--model", type=str, default="claude-sonnet-4-6")
    parser.add_argument("--expected-output-multiplier", type=float, default=0.5)
    parser.add_argument("--format", choices=["json", "markdown"], default="json")
    args = parser.parse_args(argv)

    receipt = estimate(
        original_tokens=args.original_tokens,
        compressed_tokens=args.compressed_tokens,
        model=args.model,
        expected_output_multiplier=args.expected_output_multiplier,
    )

    if args.format == "markdown":
        sys.stdout.write(render_markdown(receipt))
    else:
        json.dump(receipt, sys.stdout, indent=2)
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
