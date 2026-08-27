"""Sentinel's typed failure taxonomy.

The whole point of Week 2 is the application boundary: Claude generates text; the
application decides whether that text is *acceptable*. Every way that can go
wrong is represented here as a typed value, not a bare exception string, so the
caller can branch on it and the user gets a precise reason.

Two levels of classification:

  * FailureCategory — the coarse bucket the exercises ask for:
        input | configuration | integration | runtime | model_output
  * FailureKind — the specific thing that went wrong.

Mapping kind -> category lives in _CATEGORY so there is one source of truth.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class FailureCategory(str, Enum):
    INPUT = "input"                 # the request we were given is bad
    CONFIGURATION = "configuration" # our own setup is wrong (keys, model, env)
    INTEGRATION = "integration"     # the API call itself failed (network, auth, limits)
    RUNTIME = "runtime"             # something broke while processing (interrupted stream)
    MODEL_OUTPUT = "model_output"   # the call succeeded but the CONTENT is unusable


class FailureKind(str, Enum):
    # input
    INVALID_INPUT = "invalid_input"
    # configuration
    CONFIG_ERROR = "config_error"
    AUTH_ERROR = "auth_error"
    # integration
    RATE_LIMIT = "rate_limit"
    TIMEOUT = "timeout"
    CONTEXT_LIMIT = "context_limit"
    API_ERROR = "api_error"
    # runtime
    INTERRUPTED_STREAM = "interrupted_stream"
    # model_output
    MALFORMED_RESPONSE = "malformed_response"   # not valid JSON
    SCHEMA_INVALID = "schema_invalid"           # valid JSON, wrong shape
    UNSUPPORTED_CONTENT = "unsupported_content"  # valid shape, unsupported conclusions
    TRUNCATED_OUTPUT = "truncated_output"        # stop_reason == max_tokens
    REFUSAL = "refusal"                          # model declined


# Single source of truth: which coarse bucket each specific kind belongs to.
_CATEGORY: dict[FailureKind, FailureCategory] = {
    FailureKind.INVALID_INPUT: FailureCategory.INPUT,
    FailureKind.CONFIG_ERROR: FailureCategory.CONFIGURATION,
    FailureKind.AUTH_ERROR: FailureCategory.CONFIGURATION,
    FailureKind.RATE_LIMIT: FailureCategory.INTEGRATION,
    FailureKind.TIMEOUT: FailureCategory.INTEGRATION,
    FailureKind.CONTEXT_LIMIT: FailureCategory.INTEGRATION,
    FailureKind.API_ERROR: FailureCategory.INTEGRATION,
    FailureKind.INTERRUPTED_STREAM: FailureCategory.RUNTIME,
    FailureKind.MALFORMED_RESPONSE: FailureCategory.MODEL_OUTPUT,
    FailureKind.SCHEMA_INVALID: FailureCategory.MODEL_OUTPUT,
    FailureKind.UNSUPPORTED_CONTENT: FailureCategory.MODEL_OUTPUT,
    FailureKind.TRUNCATED_OUTPUT: FailureCategory.MODEL_OUTPUT,
    FailureKind.REFUSAL: FailureCategory.MODEL_OUTPUT,
}


@dataclass(frozen=True)
class SentinelFailure(Exception):
    """A typed, structured failure. Both an exception (can be raised) and a value
    (can be returned and inspected)."""

    kind: FailureKind
    message: str
    detail: str = ""
    request_id: str | None = None
    # For UNSUPPORTED_CONTENT: the specific support issues found.
    issues: tuple[str, ...] = field(default_factory=tuple)

    @property
    def category(self) -> FailureCategory:
        return _CATEGORY[self.kind]

    def __str__(self) -> str:
        base = f"[{self.category.value}/{self.kind.value}] {self.message}"
        if self.detail:
            base += f"\n  detail: {self.detail}"
        if self.issues:
            base += "\n  issues:\n" + "\n".join(f"    - {i}" for i in self.issues)
        if self.request_id:
            base += f"\n  request_id: {self.request_id}"
        return base
