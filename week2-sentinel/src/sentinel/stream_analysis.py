"""Section 4 — streaming vs non-streaming, and rejecting an interrupted stream.

Run it:
    uv run python -m sentinel.stream_analysis

Required exercises covered here:
  * Run Sentinel with a complete (non-streaming) response.
  * Run Sentinel with a streamed response.
  * Simulate an INTERRUPTED stream and prove the partial content is NOT accepted
    as a complete incident analysis.

Why streaming matters: a non-streaming call waits for the whole answer, so an
HTTP timeout can kill a long generation. Streaming delivers tokens as they are
produced. But a stream can also stop early — and a half-finished analysis must
never be treated as done. That is the whole point of the interruption demo.
"""

from __future__ import annotations

from .client import build_client, map_api_exception
from .config import load_settings, read_incident
from .contract import strict_schema
from .failures import FailureKind, SentinelFailure
from .prompts import SYSTEM_CONTRACT, build_user_message
from .validate import validate_input, validate_response

_SCHEMA = strict_schema()


def _request_kwargs(model, max_tokens, incident_text) -> dict:
    return dict(
        model=model,
        max_tokens=max_tokens,
        system=SYSTEM_CONTRACT,
        messages=[{"role": "user", "content": build_user_message(incident_text)}],
        output_config={"format": {"type": "json_schema", "schema": _SCHEMA}},
    )


def run_non_streaming(client, settings, incident_text):
    """A complete response: wait for everything, then validate once."""
    incident_text = validate_input(incident_text)
    try:
        resp = client.messages.create(**_request_kwargs(settings.model, settings.max_tokens, incident_text))
    except Exception as exc:
        raise map_api_exception(exc) from exc
    text = next((b.text for b in resp.content if b.type == "text"), "")
    analysis = validate_response(text, stop_reason=resp.stop_reason, request_id=resp._request_id)
    return analysis, resp.usage


def run_streaming(client, settings, incident_text, *, interrupt_after_chars: int | None = None):
    """A streamed response.

    If interrupt_after_chars is set, we stop reading the stream partway through to
    SIMULATE an interruption (a dropped connection, a killed process, a user
    hitting Ctrl-C). We then try to validate ONLY the partial text we received.

    Returns (analysis, usage) on success. On interruption, we validate the
    partial buffer, which raises a typed failure — proving partial content is
    rejected.
    """
    incident_text = validate_input(incident_text)
    parts: list[str] = []
    interrupted = False

    try:
        with client.messages.stream(**_request_kwargs(settings.model, settings.max_tokens, incident_text)) as stream:
            for chunk in stream.text_stream:
                parts.append(chunk)
                if interrupt_after_chars is not None and sum(len(p) for p in parts) >= interrupt_after_chars:
                    interrupted = True
                    break  # leave the `with` block early -> stream is closed

            if not interrupted:
                final = stream.get_final_message()
                # Streamed structured output yields a ParsedMessage, which has no
                # _request_id attribute — read it defensively.
                rid = getattr(final, "_request_id", None)
                analysis = validate_response(
                    "".join(parts), stop_reason=final.stop_reason, request_id=rid
                )
                return analysis, final.usage
    except SentinelFailure:
        raise
    except Exception as exc:
        raise map_api_exception(exc) from exc

    # We got here only if we interrupted. Feed the partial buffer to the SAME
    # validator. A truncated JSON body fails Layer 1 -> MALFORMED_RESPONSE.
    partial = "".join(parts)
    # stop_reason is deliberately None: we never received a terminal event.
    raise SentinelFailure(
        FailureKind.INTERRUPTED_STREAM,
        f"Stream was interrupted after {len(partial)} chars; partial content is not a complete analysis.",
        detail=_why_partial_is_invalid(partial),
    )


def _why_partial_is_invalid(partial: str) -> str:
    """Show WHY the partial text can't be accepted, by running it through the
    validator and reporting the layer that rejects it."""
    try:
        validate_response(partial, stop_reason=None)
        return "unexpected: partial content passed validation"
    except SentinelFailure as f:
        return f"validator rejects partial content: {f.kind.value} ({f.message})"


def main() -> int:
    settings = load_settings()
    client = build_client(settings)
    incident = read_incident("inc-104")

    print(f"→ model={settings.model}\n")

    # 1) Non-streaming
    print("=== 1. Non-streaming (complete response) ===")
    try:
        analysis, usage = run_non_streaming(client, settings, incident)
        print(f"ACCEPTED. in/out tokens = {usage.input_tokens}/{usage.output_tokens}")
        print(f"  confidence={analysis.likely_cause_assessment.confidence} "
              f"leading={analysis.likely_cause_assessment.leading_hypothesis}")
    except SentinelFailure as f:
        print("REJECTED:\n", f)

    # 2) Streaming (complete)
    print("\n=== 2. Streaming (complete response) ===")
    try:
        analysis, usage = run_streaming(client, settings, incident)
        print(f"ACCEPTED after full stream. out tokens = {usage.output_tokens}")
        print(f"  confidence={analysis.likely_cause_assessment.confidence} "
              f"leading={analysis.likely_cause_assessment.leading_hypothesis}")
    except SentinelFailure as f:
        print("REJECTED:\n", f)

    # 3) Streaming (interrupted) — must be rejected
    print("\n=== 3. Streaming INTERRUPTED (partial must be rejected) ===")
    try:
        run_streaming(client, settings, incident, interrupt_after_chars=400)
        print("!! Unexpected: partial content was accepted.")
    except SentinelFailure as f:
        print("Correctly REJECTED:\n", f)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
