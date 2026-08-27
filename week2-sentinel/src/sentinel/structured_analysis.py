"""Section 3 — structured output, and its three validation layers.

Run it:
    uv run python -m sentinel.structured_analysis            # INC-104, valid path
    uv run python -m sentinel.structured_analysis inc-205

This demonstrates the progression the curriculum asks for:

  A. Prompt-only JSON (Section 1) — the model may add fences/prose. Unreliable.
  B. A JSON Schema derived from our Pydantic contract.
  C. API-ENFORCED structured output via client.messages.parse(output_format=...),
     which guarantees Layer 1 (parse) and Layer 2 (schema) for us.
  D. Layer 3 (support) — OUR check that the conclusions are actually supported.

It also produces the required INVALID example: a response that is valid JSON of
the correct shape but whose conclusions are unsupported — proving Layer 3 rejects
what Layers 1 and 2 accept.
"""

from __future__ import annotations

import sys

from .client import build_client, map_api_exception
from .config import load_settings, read_incident
from .contract import IncidentAnalysis, strict_schema
from .failures import SentinelFailure
from .prompts import SYSTEM_CONTRACT, build_user_message
from .validate import validate_response


# The JSON Schema the API will enforce, derived from our Pydantic contract and
# made strict (additionalProperties=false, all-required). This is Path B (a JSON
# Schema) feeding Path C (API-enforced output).
ANALYSIS_SCHEMA = strict_schema()


def analyze_structured(client, model, max_tokens, incident_text) -> tuple[IncidentAnalysis, object]:
    """Path C+D: API-enforced structured output, then OUR validation pipeline.

    We use messages.create(output_config=...) rather than messages.parse() on
    purpose: parse() parses the JSON for us and, on a truncated response, raises
    a generic ValidationError before we can see stop_reason. create() hands us
    the raw text AND stop_reason, so validate_response() can classify a
    truncation as TRUNCATED_OUTPUT instead of a mystery parse error.

    Returns (analysis, usage). Raises SentinelFailure on any typed failure.
    """
    try:
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=SYSTEM_CONTRACT,
            messages=[{"role": "user", "content": build_user_message(incident_text)}],
            output_config={"format": {"type": "json_schema", "schema": ANALYSIS_SCHEMA}},
        )
    except Exception as exc:  # SDK/network/etc.
        raise map_api_exception(exc) from exc

    text = next((b.text for b in response.content if b.type == "text"), "")
    # One call through our own three layers (+ stop_reason guards).
    analysis = validate_response(
        text, stop_reason=response.stop_reason, request_id=response._request_id
    )
    return analysis, response.usage


# A hand-crafted response that is valid JSON of the correct shape but whose
# conclusions outrun the evidence — the classic Week-1 failure. We feed it
# through validate_response to prove Layer 3 rejects it.
INVALID_BUT_WELL_FORMED = """
{
  "known_facts": [
    {"fact": "The deployment caused the checkout failures because it ran just before the alert",
     "source_text": "Deployment dep-1842 completed at 10:01 UTC"}
  ],
  "assumptions": [{"assumption": "Only one cause exists", "reason": "Simplest explanation"}],
  "missing_information": [{"information": "Request-level logs", "why_needed": "To trace failures"}],
  "candidate_hypotheses": [
    {"hypothesis": "Deployment regression",
     "supporting_evidence": ["Deployment preceded the alert"],
     "contradicting_or_limiting_evidence": ["Database latency also rose"],
     "evidence_needed": ["Compare failure rates by version"]}
  ],
  "likely_cause_assessment": {
    "leading_hypothesis": "Deployment regression",
    "confidence": "high",
    "reason": "It is the confirmed root cause and definitely explains everything"
  },
  "reversible_next_actions": [
    {"action": "Roll back dep-1842", "expected_observation": "Errors drop",
     "risk_or_precondition": "None"}
  ],
  "rollback_recommendation": {
    "decision": "rollback",
    "reason": "The deployment is proven to be the cause",
    "preconditions": []
  },
  "uncertainty_statement": "None."
}
"""


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    incident_name = argv[0] if argv else "inc-104"

    settings = load_settings()
    incident_text = read_incident(incident_name)
    client = build_client(settings)

    print(f"→ model={settings.model}  incident={incident_name}\n")

    # ---- VALID path: API-enforced structured output + support check ----
    print("=== A valid structured response (Layers 1-3 pass) ===")
    try:
        analysis, usage = analyze_structured(
            client, settings.model, settings.max_tokens, incident_text
        )
        print(f"ACCEPTED. tokens in/out = {usage.input_tokens}/{usage.output_tokens}")
        lc = analysis.likely_cause_assessment
        print(f"  leading_hypothesis : {lc.leading_hypothesis}")
        print(f"  confidence         : {lc.confidence}")
        print(f"  rollback decision  : {analysis.rollback_recommendation.decision}")
        print(f"  #hypotheses        : {len(analysis.candidate_hypotheses)}")
        print(f"  uncertainty        : {analysis.uncertainty_statement[:100]}...")
        # Save the raw accepted analysis as a representative response artifact.
        from .config import INCIDENTS_DIR
        out = INCIDENTS_DIR.parent / "results" / f"{incident_name}-analysis.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(analysis.model_dump_json(indent=2), encoding="utf-8")
        print(f"  saved              : {out}")
    except SentinelFailure as f:
        # Not necessarily a bug: Layer 3 may legitimately reject a live response.
        print("REJECTED by validation:")
        print(f)

    # ---- INVALID example: valid JSON + right shape, unsupported conclusions ----
    print("\n=== An invalid response (Layers 1-2 pass, Layer 3 REJECTS) ===")
    try:
        validate_response(INVALID_BUT_WELL_FORMED, stop_reason="end_turn")
        print("!! Unexpected: the unsupported response was accepted.")
    except SentinelFailure as f:
        print("Correctly REJECTED:")
        print(f)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
