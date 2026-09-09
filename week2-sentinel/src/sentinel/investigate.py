"""Week 3 — a bounded, tool-assisted investigation of an incident.

Run it:
    uv run python -m sentinel.investigate                       # INC-104, on-call engineer
    uv run python -m sentinel.investigate inc-104 --role read-only-observer
    uv run python -m sentinel.investigate inc-104 --role external-contractor
    uv run python -m sentinel.investigate inc-104 --max-calls 1  # force the budget limit

What you will see: Claude asks for evidence, the application decides whether
each request may run (hook -> allow-list -> schema -> identity -> limits),
executes the mocked tool inside a deadline, wraps the result as untrusted
data, and hands it back. When Claude stops asking, or when the application's
budget runs out, the final JSON goes through the Week-2 validation layers.

Everything that happened is written to results/week3-<incident>-<role>.json as
a trace: that file, not the model's narrative, is the record of the run.
"""

from __future__ import annotations

import argparse
import json
import sys

from .client import build_client
from .config import INCIDENTS_DIR, load_settings, read_incident
from .tools import policy
from .tools.loop import run_investigation
from .validate import validate_input

RESULTS_DIR = INCIDENTS_DIR.parent / "results"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("incident", nargs="?", default="inc-104")
    ap.add_argument("--role", default=policy.DEFAULT_IDENTITY.role,
                    choices=sorted(policy.ROLE_PERMISSIONS) + ["unknown-role"])
    ap.add_argument("--user", default=policy.DEFAULT_IDENTITY.name)
    ap.add_argument("--max-calls", type=int, default=policy.DEFAULT_LIMITS.max_tool_calls)
    ap.add_argument("--max-seconds", type=float, default=policy.DEFAULT_LIMITS.max_wall_seconds)
    ap.add_argument("--fault", action="append", default=[], metavar="TOOL=timeout|oversized|malformed",
                    help="TEST ONLY: make a mocked tool misbehave.")
    args = ap.parse_args(argv)

    settings = load_settings()
    client = build_client(settings)
    incident = validate_input(read_incident(args.incident))
    identity = policy.Identity(name=args.user, role=args.role)
    limits = policy.LoopLimits(max_tool_calls=args.max_calls, max_wall_seconds=args.max_seconds)
    faults = dict(f.split("=", 1) for f in args.fault)

    print(f"→ model={settings.model}  incident={args.incident}  "
          f"identity={identity.name} ({identity.role})  faults={faults or 'none'}\n")

    result = run_investigation(
        client, model=settings.model, max_tokens=settings.max_tokens,
        incident_text=incident, identity=identity, limits=limits, faults=faults,
        log=lambda m: print(m),
    )

    t = result.trace
    print(f"\n=== outcome: {t.final_behaviour} ===")
    print(f"rounds={len(t.rounds)}  tool calls attempted={len(t.tool_calls)}  "
          f"executed={t.executed_calls}  elapsed={t.elapsed_seconds}s  "
          f"tokens in/out={result.usage_input_tokens}/{result.usage_output_tokens}")
    if t.limit_reached:
        print(f"limit reached      : {t.limit_reached}")
    if t.injection_flagged:
        print("injection flagged  : yes (post_tool_use hook) — passed to Claude as data only")
    if t.escalation_required:
        print("escalation required: yes (a policy hook denied a request)")

    if result.ok:
        a = result.analysis
        lc = a.likely_cause_assessment
        print(f"\nleading_hypothesis : {lc.leading_hypothesis}")
        print(f"confidence         : {lc.confidence}")
        print(f"rollback decision  : {a.rollback_recommendation.decision}")
        print(f"#hypotheses        : {len(a.candidate_hypotheses)}")
        tool_facts = [f.fact for f in a.known_facts
                      if any(n in f.source_text.lower() or n in f.fact.lower()
                             for n in ("get_service_metrics", "get_dependency_health", "search_logs"))]
        print(f"facts citing tools : {len(tool_facts)}")
        for f in tool_facts[:4]:
            print(f"   - {f[:110]}")
        print(f"uncertainty        : {a.uncertainty_statement[:140]}")
    else:
        print(f"\nFAILURE:\n{result.failure}")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    # One file per CASE, so a fault or budget run never overwrites the baseline.
    tag = f"week3-{args.incident}-{args.role}"
    if args.max_calls != policy.DEFAULT_LIMITS.max_tool_calls:
        tag += f"-calls{args.max_calls}"
    for tool, kind in sorted(faults.items()):
        tag += f"-{kind}-{tool}"
    out = RESULTS_DIR / f"{tag}.json"
    payload = {
        "model": settings.model,
        "trace": t.as_dict(),
        "analysis": result.analysis.model_dump() if result.ok else None,
        "failure": str(result.failure) if result.failure else None,
    }
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\ntrace saved -> {out.relative_to(INCIDENTS_DIR.parent)}")
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
