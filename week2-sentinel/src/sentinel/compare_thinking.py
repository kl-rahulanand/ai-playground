"""Section 6 — direct response vs extended thinking, on one difficult case.

Run it:
    uv run python -m sentinel.compare_thinking

We run INC-104 (competing hypotheses, no confirmed cause) two ways on the SAME
model and compare quality, latency, tokens, and estimated cost:

  1. DIRECT       — no thinking parameter; the model answers immediately.
  2. THINKING     — extended thinking on. On Haiku 4.5 that means
                    thinking={"type":"enabled","budget_tokens": N} (adaptive
                    thinking and the effort control are 4.6+ / Opus-tier only;
                    Haiku uses the budget form).

The lesson to check: more thinking may improve structure and the list of missing
evidence, but it does NOT invent evidence that wasn't in the incident. A good
result is BOTH runs landing on low confidence / no single confirmed cause.
"""

from __future__ import annotations

from .client import build_client, map_api_exception
from .config import load_settings, read_incident
from .contract import strict_schema
from .failures import SentinelFailure
from .metrics import Timer, estimate_cost
from .prompts import SYSTEM_CONTRACT, build_user_message
from .validate import validate_response

_SCHEMA = strict_schema()


def _run(client, model, max_tokens, incident_text, *, thinking: bool):
    kwargs = dict(
        model=model,
        max_tokens=max_tokens,
        system=SYSTEM_CONTRACT,
        messages=[{"role": "user", "content": build_user_message(incident_text)}],
        output_config={"format": {"type": "json_schema", "schema": _SCHEMA}},
    )
    if thinking:
        # budget must be < max_tokens and >= 1024 on Haiku.
        kwargs["thinking"] = {"type": "enabled", "budget_tokens": max(1024, max_tokens // 2)}

    with Timer() as t:
        try:
            resp = client.messages.create(**kwargs)
        except Exception as exc:
            raise map_api_exception(exc) from exc

    text = next((b.text for b in resp.content if b.type == "text"), "")
    thinking_present = any(b.type == "thinking" for b in resp.content)
    analysis = validate_response(text, stop_reason=resp.stop_reason, request_id=resp._request_id)
    return analysis, resp.usage, t.seconds, thinking_present


def _summarize(name, analysis, usage, secs, thinking_present, model):
    cost = estimate_cost(model, usage)
    lc = analysis.likely_cause_assessment
    missing = len(analysis.missing_information)
    hyps = len(analysis.candidate_hypotheses)
    print(f"\n[{name}]")
    print(f"  thinking blocks present : {thinking_present}")
    print(f"  latency                 : {secs:.1f}s")
    print(f"  input / output tokens   : {usage.input_tokens} / {usage.output_tokens}")
    print(f"  estimated cost          : ${cost.total:.5f}")
    print(f"  leading_hypothesis      : {lc.leading_hypothesis}")
    print(f"  confidence              : {lc.confidence}")
    print(f"  # hypotheses            : {hyps}")
    print(f"  # missing_information   : {missing}")
    print(f"  rollback decision       : {analysis.rollback_recommendation.decision}")
    return cost


def main() -> int:
    settings = load_settings()
    client = build_client(settings)
    incident = read_incident("inc-104")
    model = settings.model
    print(f"→ model={model}  case=inc-104 (difficult: competing hypotheses)")

    results = {}
    for name, thinking in (("DIRECT", False), ("THINKING", True)):
        try:
            analysis, usage, secs, tp = _run(client, model, settings.max_tokens, incident, thinking=thinking)
            results[name] = _summarize(name, analysis, usage, secs, tp, model)
        except SentinelFailure as f:
            print(f"\n[{name}] FAILED:\n", f)

    if len(results) == 2:
        d, th = results["DIRECT"], results["THINKING"]
        print("\n--- comparison ---")
        print(f"  extra output tokens with thinking : {th.output_tokens - d.output_tokens}")
        print(f"  extra cost with thinking          : ${th.total - d.total:.5f}")
        print("  takeaway: thinking changes token/latency/cost; check above whether it")
        print("            changed the CONCLUSION (it should still be cautious — thinking")
        print("            does not create evidence the incident never contained).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
