"""Three layers of validation.

The milestone diagram has three distinct gates between a raw response and an
accepted analysis. They are NOT the same check, and a response can pass the first
two and still fail the third:

  Layer 1  PARSE      -> is it valid JSON at all?          (MALFORMED_RESPONSE)
  Layer 2  SCHEMA     -> does it match the contract shape? (SCHEMA_INVALID)
  Layer 3  SUPPORT    -> are the conclusions actually      (UNSUPPORTED_CONTENT)
                         supported by the evidence?

Layer 3 is the Week-2 punchline: "A response with valid JSON can still contain an
unsupported conclusion." Layers 1-2 are mechanical (the SDK/Pydantic do them);
Layer 3 encodes Sentinel's reasoning discipline as executable rules.
"""

from __future__ import annotations

import json
import re

from pydantic import ValidationError

from .contract import IncidentAnalysis
from .failures import FailureKind, SentinelFailure

# ---------------------------------------------------------------------------
# Layer 0 — input (before we ever call the API)
# ---------------------------------------------------------------------------

def validate_input(incident_text: str) -> str:
    """Guard the *input* to Sentinel. A bad incident is an INPUT failure — we
    catch it before spending a request. Returns the cleaned text."""
    text = (incident_text or "").strip()
    if len(text) < 20:
        raise SentinelFailure(
            FailureKind.INVALID_INPUT,
            "Incident text is empty or too short to analyse.",
            detail=f"got {len(text)} chars, need >= 20",
        )
    return text


# ---------------------------------------------------------------------------
# Layer 1 — parse
# ---------------------------------------------------------------------------

def extract_json(text: str) -> dict:
    """Pull a JSON object out of raw model text.

    Handles the common reality that a model may wrap JSON in ```json fences or
    add stray prose (exactly what Haiku did in Section 1). If we can't recover a
    JSON object, that's a MALFORMED_RESPONSE — a model-output failure.
    """
    cleaned = text.strip()

    # Strip a leading/trailing markdown code fence if present.
    if cleaned.startswith("```"):
        # drop the first fence line (``` or ```json) and any trailing fence
        cleaned = cleaned.split("\n", 1)[-1] if "\n" in cleaned else cleaned
        if cleaned.rstrip().endswith("```"):
            cleaned = cleaned.rstrip()[: -3]
    cleaned = cleaned.strip()

    # Fall back to the outermost braces if there's still surrounding prose.
    if not cleaned.startswith("{"):
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise SentinelFailure(
                FailureKind.MALFORMED_RESPONSE,
                "Response did not contain a JSON object.",
                detail=text[:200],
            )
        cleaned = cleaned[start : end + 1]

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise SentinelFailure(
            FailureKind.MALFORMED_RESPONSE,
            "Response was not valid JSON.",
            detail=f"{exc}",
        ) from exc

    if not isinstance(data, dict):
        raise SentinelFailure(
            FailureKind.MALFORMED_RESPONSE,
            f"Top-level JSON was {type(data).__name__}, expected object.",
        )
    return data


# ---------------------------------------------------------------------------
# Layer 2 — schema
# ---------------------------------------------------------------------------

def to_analysis(data: dict) -> IncidentAnalysis:
    """Validate the parsed dict against the contract. Wrong shape -> SCHEMA_INVALID."""
    try:
        return IncidentAnalysis.model_validate(data)
    except ValidationError as exc:
        # Summarise the first few field errors for a readable message.
        errs = exc.errors()[:5]
        summary = "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in errs)
        raise SentinelFailure(
            FailureKind.SCHEMA_INVALID,
            f"Response JSON did not match the contract ({len(exc.errors())} error(s)).",
            detail=summary,
        ) from exc


# ---------------------------------------------------------------------------
# Layer 3 — support (the interesting one)
# ---------------------------------------------------------------------------

# Words that turn a stated 'fact' into an interpretation, or signal overclaiming.
_CAUSAL_WORDS = ("caused", "because", "due to", "resulted in", "led to")
_CERTAINTY_WORDS = ("confirmed root cause", "definitely", "proven", "certainly the cause",
                    "conclusively", "without a doubt")

# Negations that INVERT a certainty word. "no confirmed root cause" and "not
# proven" are the *correct* cautious statements, so they must not be flagged.
_NEGATORS = ("no", "not", "n't", "without", "cannot", "can't", "never", "un",
             "lacks", "lack", "isn't", "aren't", "unconfirmed", "unproven",
             "insufficient", "hasn't", "haven't")


def _norm(s: str) -> str:
    return " ".join(s.lower().split())


def _unnegated_certainty(text: str) -> list[str]:
    """Return certainty phrases used AS assertions (not negated) in text.

    For each certainty phrase, we look at a short window of words before each
    occurrence; if any negator appears there, the phrase is being denied, not
    asserted, and we don't flag it. This kills the 'no confirmed root cause'
    false positive while still catching a bare 'confirmed root cause'.
    """
    norm = _norm(text)
    flagged: list[str] = []
    for phrase in _CERTAINTY_WORDS:
        for m in re.finditer(re.escape(phrase), norm):
            window = norm[max(0, m.start() - 25): m.start()]
            window_words = re.findall(r"[a-z']+", window)
            if any(neg in window_words for neg in _NEGATORS):
                continue  # negated -> a cautious statement, not overclaiming
            flagged.append(phrase)
            break  # one flag per phrase is enough
    return flagged


def check_support(analysis: IncidentAnalysis) -> list[str]:
    """Return a list of support issues. Empty list == conclusions are supported.

    These are heuristics, not proofs — but they catch the exact failure modes
    Week 1 identified: confident conclusions that outrun the evidence, causal
    claims dressed up as facts, and rollback calls made on weak evidence.
    """
    issues: list[str] = []
    a = analysis
    hyps = a.candidate_hypotheses
    hyp_texts = [_norm(h.hypothesis) for h in hyps]
    lead = a.likely_cause_assessment.leading_hypothesis
    conf = a.likely_cause_assessment.confidence

    # R1: a named leading hypothesis must actually be one of the candidates.
    if lead is not None:
        lnorm = _norm(lead)
        if not any(lnorm in ht or ht in lnorm for ht in hyp_texts):
            issues.append(
                f"leading_hypothesis is not among candidate_hypotheses: {lead!r}"
            )

    # R2: high confidence requires a leading hypothesis with supporting evidence.
    if conf == "high":
        if lead is None:
            issues.append("confidence is 'high' but no leading_hypothesis is named.")
        else:
            lead_h = next((h for h in hyps if _norm(h.hypothesis) in _norm(lead)
                           or _norm(lead) in _norm(h.hypothesis)), None)
            if lead_h and not lead_h.supporting_evidence:
                issues.append("confidence is 'high' but the leading hypothesis has no supporting_evidence.")
            if lead_h and lead_h.evidence_needed:
                issues.append(
                    "confidence is 'high' but the leading hypothesis still lists evidence_needed "
                    "(the case is not actually closed)."
                )

    # R3: don't recommend an irreversible rollback on weak/ambiguous evidence.
    dec = a.rollback_recommendation.decision
    if dec == "rollback":
        if conf == "low":
            issues.append("rollback recommended at 'low' confidence (irreversible action on weak evidence).")
        if lead is None:
            issues.append("rollback recommended with no leading_hypothesis identified.")

    # R4: every hypothesis needs at least some evidentiary content.
    for i, h in enumerate(hyps):
        if not h.supporting_evidence and not h.evidence_needed:
            issues.append(f"hypothesis[{i}] has neither supporting_evidence nor evidence_needed.")

    # R5: 'facts' must be observations, not causal interpretations.
    for f in a.known_facts:
        if any(w in _norm(f.fact) for w in _CAUSAL_WORDS):
            issues.append(f"stated fact contains causal language (belongs in a hypothesis): {f.fact!r}")

    # R6: no overclaiming certainty language anywhere in the reasoning text.
    haystack = " ".join([
        a.likely_cause_assessment.reason,
        a.rollback_recommendation.reason,
        a.uncertainty_statement,
        *(h.hypothesis for h in hyps),
    ])
    for w in _unnegated_certainty(haystack):
        issues.append(f"overclaiming certainty language used (as an assertion): {w!r}")

    # R7: uncertainty must actually be stated.
    if len(a.uncertainty_statement.strip()) < 15:
        issues.append("uncertainty_statement is empty or trivially short.")

    return issues


# ---------------------------------------------------------------------------
# Top-level: run all three layers
# ---------------------------------------------------------------------------

def validate_response(
    text: str,
    *,
    stop_reason: str | None = None,
    request_id: str | None = None,
) -> IncidentAnalysis:
    """Run the full pipeline. Returns a validated, supported analysis or raises
    the appropriate typed SentinelFailure."""

    # Guard: a truncated response is never acceptable, however good it looks.
    if stop_reason == "max_tokens":
        raise SentinelFailure(
            FailureKind.TRUNCATED_OUTPUT,
            "Output was truncated (stop_reason=max_tokens); it is incomplete.",
            request_id=request_id,
        )
    if stop_reason == "refusal":
        raise SentinelFailure(
            FailureKind.REFUSAL,
            "Model refused the request.",
            request_id=request_id,
        )

    data = extract_json(text)                # Layer 1
    analysis = to_analysis(data)             # Layer 2
    issues = check_support(analysis)         # Layer 3
    if issues:
        raise SentinelFailure(
            FailureKind.UNSUPPORTED_CONTENT,
            "Response is valid JSON of the right shape, but its conclusions are "
            "not supported by the evidence.",
            request_id=request_id,
            issues=tuple(issues),
        )
    return analysis
