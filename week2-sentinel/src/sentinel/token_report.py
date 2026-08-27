"""Section 7 — tokens, context, and cost for one request.

Run it:
    uv run python -m sentinel.token_report

Records the full metadata the exercise asks for: model, input tokens, output
tokens, thinking tokens (when applicable), max output tokens, latency, estimated
cost, and stop reason. Uses the token-counting endpoint to count input BEFORE
sending, then compares to the actual usage.
"""

from __future__ import annotations

import json

from .client import build_client, map_api_exception
from .config import INCIDENTS_DIR, load_settings, read_incident
from .contract import strict_schema
from .metrics import Timer, estimate_cost
from .prompts import SYSTEM_CONTRACT, build_user_message


def main() -> int:
    settings = load_settings()
    client = build_client(settings)
    incident = read_incident("inc-104")
    model = settings.model
    messages = [{"role": "user", "content": build_user_message(incident)}]

    # --- Token counting BEFORE the request (no generation, cheap) ---
    counted = client.messages.count_tokens(model=model, system=SYSTEM_CONTRACT, messages=messages)
    print(f"count_tokens (system+messages only): {counted.input_tokens} input tokens")
    print("  note: this does NOT include the output_config JSON schema, which is")
    print("  sent with the real request and adds input tokens — see the gap below.\n")

    # --- The real request, timed ---
    with Timer() as t:
        try:
            resp = client.messages.create(
                model=model,
                max_tokens=settings.max_tokens,
                system=SYSTEM_CONTRACT,
                messages=messages,
                output_config={"format": {"type": "json_schema", "schema": strict_schema()}},
            )
        except Exception as exc:
            raise map_api_exception(exc) from exc

    cost = estimate_cost(model, resp.usage)
    record = {
        "model": resp.model,
        "counted_input_tokens_no_schema": counted.input_tokens,
        "actual_input_tokens_with_schema": resp.usage.input_tokens,
        "schema_token_overhead": resp.usage.input_tokens - counted.input_tokens,
        "output_tokens": resp.usage.output_tokens,
        "thinking_tokens": "n/a (thinking not enabled; when on, counted within output_tokens on Haiku)",
        "max_output_tokens_limit": settings.max_tokens,
        "latency_seconds": round(t.seconds, 2),
        "stop_reason": resp.stop_reason,
        "estimated_cost_usd": round(cost.total, 6),
        "cost_breakdown_usd": {
            "input": round(cost.input_cost, 6),
            "output": round(cost.output_cost, 6),
        },
    }

    print("=== token / latency / cost record ===")
    for k, v in record.items():
        print(f"  {k}: {v}")

    out = INCIDENTS_DIR.parent / "results" / "token-record.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(record, indent=2), encoding="utf-8")
    print(f"\nsaved {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
