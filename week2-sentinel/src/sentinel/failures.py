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
    TOOL = "tool"                   # Week 3: a tool the model requested could not run safely


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

    # tool (Week 3) — a tool the model requested could not run safely.
    # The first five are RECOVERABLE: the loop returns them to Claude as an
    # error tool_result and lets it adapt. The last two are TERMINAL: no
    # further tool may execute; the loop moves straight to finalisation (one
    # last round with tool_choice=none) or stops. The model gets no say.
    TOOL_NOT_ALLOWED = "tool_not_allowed"       # not on the application allow-list
    TOOL_INPUT_INVALID = "tool_input_invalid"   # failed the application input schema
    TOOL_UNAUTHORIZED = "tool_unauthorized"     # caller identity lacks permission
    TOOL_EXEC_TIMEOUT = "tool_exec_timeout"     # the mocked tool exceeded its deadline
    TOOL_RESULT_INVALID = "tool_result_invalid" # tool returned malformed/oversized data
    TOOL_LIMIT_EXCEEDED = "tool_limit_exceeded" # max calls / max wall-time reached (terminal)
    TOOL_BLOCKED_BY_POLICY = "tool_blocked_by_policy"  # deterministic hook refused it (terminal)


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
    FailureKind.TOOL_NOT_ALLOWED: FailureCategory.TOOL,
    FailureKind.TOOL_INPUT_INVALID: FailureCategory.TOOL,
    FailureKind.TOOL_UNAUTHORIZED: FailureCategory.TOOL,
    FailureKind.TOOL_EXEC_TIMEOUT: FailureCategory.TOOL,
    FailureKind.TOOL_RESULT_INVALID: FailureCategory.TOOL,
    FailureKind.TOOL_LIMIT_EXCEEDED: FailureCategory.TOOL,
    FailureKind.TOOL_BLOCKED_BY_POLICY: FailureCategory.TOOL,
}

# Which tool failures are RECOVERABLE (returned to Claude as an error
# tool_result so it can adapt) versus TERMINAL (the loop must stop). This is a
# single source of truth the loop consults — the model cannot change it.
RECOVERABLE_TOOL_KINDS: frozenset[FailureKind] = frozenset({
    FailureKind.TOOL_NOT_ALLOWED,
    FailureKind.TOOL_INPUT_INVALID,
    FailureKind.TOOL_UNAUTHORIZED,
    FailureKind.TOOL_EXEC_TIMEOUT,
    FailureKind.TOOL_RESULT_INVALID,
})
TERMINAL_TOOL_KINDS: frozenset[FailureKind] = frozenset({
    FailureKind.TOOL_LIMIT_EXCEEDED,
    FailureKind.TOOL_BLOCKED_BY_POLICY,
})


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


@dataclass(frozen=True)
class ToolError(Exception):
    """A problem with a *single* tool request, raised inside the tool layer.

    Distinct from SentinelFailure on purpose. A SentinelFailure aborts the whole
    request; a ToolError describes one tool call that could not run. The loop
    decides what to do with it based on `kind`:

      * RECOVERABLE_TOOL_KINDS -> serialise as an error tool_result, hand it back
        to Claude, and continue. The model must cope with the failure.
      * TERMINAL_TOOL_KINDS    -> no further tool execution. The loop either
        finalises (asks for the answer with tools disabled) or stops.
        The model gets no say.

    `kind` always belongs to FailureCategory.TOOL.
    """

    kind: FailureKind
    message: str
    detail: str = ""

    @property
    def is_terminal(self) -> bool:
        return self.kind in TERMINAL_TOOL_KINDS

    def as_tool_result_payload(self) -> dict:
        """The JSON body we return to Claude for a recoverable tool failure.

        Note it is a plain data object with an `error` field — NOT an instruction.
        Claude sees that the tool failed and why, and nothing more."""
        payload = {"error": self.kind.value, "message": self.message}
        if self.detail:
            payload["detail"] = self.detail
        return payload

    def __str__(self) -> str:
        base = f"[tool/{self.kind.value}] {self.message}"
        if self.detail:
            base += f" ({self.detail})"
        return base
