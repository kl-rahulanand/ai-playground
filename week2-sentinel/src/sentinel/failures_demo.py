"""Section 4 (cont.) — exercise every failure category deterministically.

Run it:
    uv run python -m sentinel.failures_demo          # offline demos only
    uv run python -m sentinel.failures_demo --live   # also trigger live ones

Exercise 5 asks us to classify failures as input / configuration / integration /
runtime / model-output. This script triggers a representative failure for each
category and prints the typed SentinelFailure so you can see the classification.

Most are triggered OFFLINE (no API call, fully deterministic). Two need the API
(auth + truncation); run with --live to include them.
"""

from __future__ import annotations

import sys

from .client import build_client, map_api_exception
from .config import Settings, load_settings, read_incident
from .contract import strict_schema
from .failures import FailureCategory, FailureKind, SentinelFailure, _CATEGORY
from .prompts import SYSTEM_CONTRACT, build_user_message
from .validate import validate_input, validate_response

# Valid JSON but WRONG shape (missing required fields) -> SCHEMA_INVALID.
WRONG_SHAPE = '{"known_facts": "should be a list", "uncertainty_statement": 42}'
# Not JSON at all -> MALFORMED_RESPONSE.
NOT_JSON = "I'm sorry, I can't help with that."
# Valid + right shape but unsupported -> UNSUPPORTED_CONTENT (imported).
from .structured_analysis import INVALID_BUT_WELL_FORMED


def _show(label: str, fn) -> None:
    try:
        fn()
        print(f"  {label}: (no failure raised!)")
    except SentinelFailure as f:
        print(f"  {label}: [{f.category.value}/{f.kind.value}] {f.message}")


def offline_demos() -> None:
    print("OFFLINE failure demonstrations:")
    _show("INPUT       ", lambda: validate_input("   "))
    _show("MODEL_OUTPUT(malformed)", lambda: validate_response(NOT_JSON, stop_reason="end_turn"))
    _show("MODEL_OUTPUT(schema)   ", lambda: validate_response(WRONG_SHAPE, stop_reason="end_turn"))
    _show("MODEL_OUTPUT(unsupported)", lambda: validate_response(INVALID_BUT_WELL_FORMED, stop_reason="end_turn"))
    _show("MODEL_OUTPUT(truncated) ", lambda: validate_response("{...}", stop_reason="max_tokens"))
    _show("MODEL_OUTPUT(refusal)   ", lambda: validate_response("{...}", stop_reason="refusal"))

    # Configuration: no credential.
    def _no_cred():
        import os
        saved = os.environ.pop("ANTHROPIC_AUTH_TOKEN", None), os.environ.pop("ANTHROPIC_API_KEY", None)
        try:
            load_settings(require_key=True)
        finally:  # restore
            if saved[0]: os.environ["ANTHROPIC_AUTH_TOKEN"] = saved[0]
            if saved[1]: os.environ["ANTHROPIC_API_KEY"] = saved[1]
    from .config import ConfigError
    try:
        _no_cred()
    except ConfigError as e:
        print(f"  CONFIGURATION: [configuration/config_error] {str(e).splitlines()[0]}")


def live_demos() -> None:
    print("\nLIVE failure demonstrations (--live):")
    settings = load_settings()

    # AUTH_ERROR (configuration): a deliberately bad token.
    bad = Settings(api_key=None, auth_token="sk-ant-oat01-BOGUS", model=settings.model,
                   max_tokens=64, base_url=settings.base_url)
    try:
        build_client(bad).with_options(max_retries=0).messages.create(
            model=settings.model, max_tokens=16,
            messages=[{"role": "user", "content": "hi"}])
    except Exception as exc:
        f = map_api_exception(exc)
        print(f"  AUTH        : [{f.category.value}/{f.kind.value}] {f.message}")

    # TRUNCATED_OUTPUT (model_output): a tiny max_tokens on a real request.
    client = build_client(settings)
    try:
        resp = client.messages.create(
            model=settings.model, max_tokens=16,
            system=SYSTEM_CONTRACT,
            messages=[{"role": "user", "content": build_user_message(read_incident("inc-104"))}],
            output_config={"format": {"type": "json_schema", "schema": strict_schema()}},
        )
        text = next((b.text for b in resp.content if b.type == "text"), "")
        validate_response(text, stop_reason=resp.stop_reason)
        print("  TRUNCATED   : (completed within 16 tokens?!)")
    except SentinelFailure as f:
        print(f"  TRUNCATED   : [{f.category.value}/{f.kind.value}] {f.message}")


def print_taxonomy() -> None:
    print("\nFull taxonomy (kind -> category):")
    by_cat: dict[FailureCategory, list[str]] = {}
    for kind, cat in _CATEGORY.items():
        by_cat.setdefault(cat, []).append(kind.value)
    for cat in FailureCategory:
        print(f"  {cat.value:14s} <- {', '.join(by_cat.get(cat, []))}")


def main() -> int:
    offline_demos()
    if "--live" in sys.argv[1:]:
        live_demos()
    print_taxonomy()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
