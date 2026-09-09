"""The bounded tool-execution loop.

This is the "escort" from tools/__init__.py: it walks Claude up to the guard,
counts how many times it may ask, watches the clock, and decides when the
conversation is over. Claude decides WHICH evidence to ask for; this file
decides WHETHER and HOW MUCH.

Lifecycle (Part 3 of the milestone):

    1. Send the incident + tool definitions to Claude.
    2. Inspect the response.
    3. tool_use? -> for each requested tool:
         hook (destructive?) -> allow-list -> schema -> identity/permissions
         -> value limits -> bounded execution -> output validation -> hook (wrap)
    4. Return one tool_result per tool_use (errors included, is_error=True).
    5. Ask Claude to continue.
    6. Stop on a final answer, or when an APPLICATION limit is reached.

Termination is guaranteed by three independent counters the model cannot see:
max_rounds (API round-trips), max_tool_calls (executions), max_wall_seconds
(clock). Any one of them ends the loop.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field

from ..contract import IncidentAnalysis, strict_schema
from ..failures import FailureKind, SentinelFailure, ToolError
from ..prompts import INVESTIGATION_SYSTEM_PROMPT, build_investigation_message
from ..validate import validate_response
from . import hooks, policy
from .guards import (
    ToolRequest,
    authorize,
    check_allowlisted,
    enforce_value_limits,
    execute_bounded,
    validate_input,
    validate_output,
)
from .registry import TOOL_SPECS, ToolSpec

# The final answer is API-enforced JSON of the Week-2 contract, then run
# through our own three validation layers. Tools and structured output can be
# combined on one request; tool_use turns in between are unaffected.
_ANALYSIS_FORMAT = {"format": {"type": "json_schema", "schema": strict_schema()}}


# ---------------------------------------------------------------------------
# Trace records — the application's own account of what happened. These, not
# the model's narrative, are the evidence of what Sentinel did.
# ---------------------------------------------------------------------------

@dataclass
class ToolCallRecord:
    """One requested tool call, in the format Part 4 asks us to record."""
    tool_use_id: str
    requested_action: dict                 # {"tool": name, "input": {...}}
    validation: str = "not_reached"        # allow-list + schema + value limits
    authorization: str = "not_reached"     # identity / role check
    execution: str = "not_reached"         # ran / timed out / rejected output
    returned_to_model: str = ""            # "data" | "error:<kind>"
    hook_decisions: list[dict] = field(default_factory=list)
    duration_ms: int = 0

    def as_dict(self) -> dict:
        return self.__dict__.copy()


@dataclass
class InvestigationTrace:
    identity: dict
    limits: dict
    rounds: list[dict] = field(default_factory=list)
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    limit_reached: str | None = None       # which limit ended tool use, if any
    escalation_required: bool = False      # a policy hook fired
    injection_flagged: bool = False        # a post-hook flagged tool output
    elapsed_seconds: float = 0.0
    final_behaviour: str = ""

    @property
    def executed_calls(self) -> int:
        return sum(1 for r in self.tool_calls if r.execution.startswith("ran"))

    def as_dict(self) -> dict:
        d = self.__dict__.copy()
        d["tool_calls"] = [r.as_dict() for r in self.tool_calls]
        d["executed_calls"] = self.executed_calls
        return d


@dataclass
class InvestigationResult:
    analysis: IncidentAnalysis | None
    failure: SentinelFailure | None
    trace: InvestigationTrace
    usage_input_tokens: int = 0
    usage_output_tokens: int = 0

    @property
    def ok(self) -> bool:
        return self.analysis is not None


# ---------------------------------------------------------------------------
# The gate: everything between "Claude asked" and "Claude gets a tool_result".
# ---------------------------------------------------------------------------

@dataclass
class _Outcome:
    content: str
    is_error: bool
    error: ToolError | None
    record: ToolCallRecord


class ToolGate:
    """Applies hooks + guards to one tool request and produces the tool_result.

    `faults` is a TEST-ONLY seam: {tool_name: "timeout" | "oversized" |
    "malformed"} makes the mocked backend misbehave so the guards can be
    exercised deterministically. Production callers never set it.
    """

    def __init__(self, identity: policy.Identity, limits: policy.LoopLimits,
                 faults: dict[str, str] | None = None) -> None:
        self.identity = identity
        self.limits = limits
        self.faults = faults or {}
        self.calls_attempted = 0

    def _execute(self, spec: ToolSpec, args: dict) -> dict:
        fault = self.faults.get(spec.name)
        if fault == "timeout":
            def slow(_args: dict) -> dict:
                time.sleep(self.limits.tool_timeout_seconds + 1.0)
                return {}
            spec = ToolSpec(spec.name, spec.description, spec.input_model, slow)
        elif fault == "oversized":
            spec = ToolSpec(spec.name, spec.description, spec.input_model,
                            lambda a: {**spec.execute(a), "padding": "x" * 10_000})
        elif fault == "malformed":
            spec = ToolSpec(spec.name, spec.description, spec.input_model,
                            lambda a: ["not", "an", "object"])
        return execute_bounded(spec, args, timeout_seconds=self.limits.tool_timeout_seconds)

    def handle(self, tool_use_id: str, name: str, raw_input: object) -> _Outcome:
        self.calls_attempted += 1
        started = time.monotonic()
        rec = ToolCallRecord(
            tool_use_id=tool_use_id,
            requested_action={"tool": name, "input": raw_input},
        )
        req = ToolRequest(tool_use_id=tool_use_id, name=name,
                          raw_input=raw_input if isinstance(raw_input, dict) else {},
                          identity=self.identity)
        try:
            # 0. Deterministic hook FIRST: destructive names never get further.
            pre = hooks.pre_tool_use(name, raw_input)
            rec.hook_decisions.append(pre.as_dict())
            if not pre.allowed:
                rec.validation = "rejected: blocked by policy hook"
                raise ToolError(FailureKind.TOOL_BLOCKED_BY_POLICY, pre.reason,
                                detail=pre.policy)

            # 1. Allow-list, 2. schema, 4. value limits  -> "validation"
            spec = check_allowlisted(req)
            args = validate_input(spec, raw_input)
            enforce_value_limits(spec, args)
            rec.validation = "passed"

            # 3. Identity + permissions -> "authorization"
            authorize(req, args)
            rec.authorization = "passed"

            # 5. Bounded execution, 6. output validation -> "execution"
            result = self._execute(spec, args)
            text = validate_output(spec, result, max_bytes=self.limits.max_result_bytes)
            rec.execution = "ran"

            # 7. Post hook: wrap as untrusted data, flag instruction-like text.
            content, post = hooks.post_tool_use(name, text)
            rec.hook_decisions.append(post.as_dict())
            rec.returned_to_model = "data"
            rec.duration_ms = int((time.monotonic() - started) * 1000)
            return _Outcome(content=content, is_error=False, error=None, record=rec)

        except ToolError as err:
            # Fill in whichever stage failed so the record is self-explanatory.
            if rec.validation == "not_reached":
                rec.validation = f"rejected: {err.kind.value}"
            elif rec.authorization == "not_reached":
                rec.authorization = f"denied: {err.kind.value}"
            elif rec.execution == "not_reached":
                rec.execution = f"failed: {err.kind.value}"
            rec.returned_to_model = f"error:{err.kind.value}"
            rec.duration_ms = int((time.monotonic() - started) * 1000)
            return _Outcome(
                content=json.dumps(err.as_tool_result_payload()),
                is_error=True, error=err, record=rec,
            )


# ---------------------------------------------------------------------------
# The loop
# ---------------------------------------------------------------------------

def run_investigation(
    client,
    *,
    model: str,
    max_tokens: int,
    incident_text: str,
    identity: policy.Identity = policy.DEFAULT_IDENTITY,
    limits: policy.LoopLimits = policy.DEFAULT_LIMITS,
    faults: dict[str, str] | None = None,
    log=None,
) -> InvestigationResult:
    """Run one bounded, validated investigation. Never raises for tool or model
    problems — every outcome is an InvestigationResult with a trace."""
    say = log or (lambda *_: None)

    # Effective budget = min(loop limit, role limit). Unknown role -> 0 calls.
    perms = policy.permissions_for(identity)
    if perms is not None:
        limits = limits.capped_by(perms)
    else:
        limits = policy.LoopLimits(max_tool_calls=0, max_rounds=limits.max_rounds,
                                   max_wall_seconds=limits.max_wall_seconds,
                                   tool_timeout_seconds=limits.tool_timeout_seconds,
                                   max_result_bytes=limits.max_result_bytes)

    trace = InvestigationTrace(identity=identity.__dict__.copy(), limits=limits.__dict__.copy())
    gate = ToolGate(identity, limits, faults)
    tools = [TOOL_SPECS[n].definition for n in sorted(policy.ALLOWED_TOOLS)]
    messages: list[dict] = [{"role": "user", "content": build_investigation_message(incident_text)}]

    started = time.monotonic()
    deadline = started + limits.max_wall_seconds
    in_tokens = out_tokens = 0
    finalising = False           # True once tools are switched off for good
    result: InvestigationResult | None = None

    def finish(analysis, failure, behaviour: str) -> InvestigationResult:
        trace.elapsed_seconds = round(time.monotonic() - started, 2)
        trace.final_behaviour = behaviour
        return InvestigationResult(analysis, failure, trace, in_tokens, out_tokens)

    for round_no in range(1, limits.max_rounds + 1):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            trace.limit_reached = trace.limit_reached or "max_wall_seconds"
            return finish(None, SentinelFailure(
                FailureKind.TOOL_LIMIT_EXCEEDED,
                f"Investigation exceeded {limits.max_wall_seconds:.0f}s wall-clock limit.",
            ), "stopped: wall-clock limit reached before a final answer")

        tool_choice = {"type": "none"} if finalising else {"type": "auto"}
        say(f"round {round_no}: calling Claude (tool_choice={tool_choice['type']}, "
            f"{remaining:.0f}s left, {gate.calls_attempted}/{limits.max_tool_calls} calls used)")
        try:
            response = client.with_options(timeout=remaining).messages.create(
                model=model, max_tokens=max_tokens,
                system=INVESTIGATION_SYSTEM_PROMPT,
                tools=tools, tool_choice=tool_choice,
                output_config=_ANALYSIS_FORMAT,
                messages=messages,
            )
        except Exception as exc:
            from ..client import map_api_exception
            return finish(None, map_api_exception(exc), "stopped: API failure")

        in_tokens += response.usage.input_tokens
        out_tokens += response.usage.output_tokens
        tool_blocks = [b for b in response.content if b.type == "tool_use"]
        trace.rounds.append({
            "round": round_no, "stop_reason": response.stop_reason,
            "tool_uses": [b.name for b in tool_blocks],
        })

        # ---- final answer path -------------------------------------------
        if response.stop_reason != "tool_use":
            text = next((b.text for b in response.content if b.type == "text"), "")
            try:
                analysis = validate_response(text, stop_reason=response.stop_reason,
                                             request_id=getattr(response, "_request_id", None))
            except SentinelFailure as f:
                return finish(None, f, f"stopped: final answer rejected ({f.kind.value})")
            behaviour = "completed: validated analysis"
            if trace.limit_reached:
                behaviour += f" after {trace.limit_reached} limit"
            if trace.escalation_required:
                behaviour += "; escalation required (policy hook fired)"
            return finish(analysis, None, behaviour)

        # ---- tool_use path ------------------------------------------------
        messages.append({"role": "assistant", "content": response.content})
        results: list[dict] = []
        for block in tool_blocks:
            if gate.calls_attempted >= limits.max_tool_calls:
                # The budget is spent. Refuse WITHOUT executing, record it, and
                # switch tools off for the rest of the conversation.
                err = ToolError(FailureKind.TOOL_LIMIT_EXCEEDED,
                                f"Tool-call budget of {limits.max_tool_calls} exhausted; "
                                "answer from the evidence already gathered.")
                rec = ToolCallRecord(block.id, {"tool": block.name, "input": block.input},
                                     validation="not_evaluated: budget exhausted",
                                     authorization="not_evaluated",
                                     execution="refused",
                                     returned_to_model=f"error:{err.kind.value}")
                trace.tool_calls.append(rec)
                trace.limit_reached = trace.limit_reached or "max_tool_calls"
                finalising = True
                say(f"  ✗ {block.name}: {err.message}")
                results.append({"type": "tool_result", "tool_use_id": block.id,
                                "content": json.dumps(err.as_tool_result_payload()),
                                "is_error": True})
                continue

            outcome = gate.handle(block.id, block.name, block.input)
            trace.tool_calls.append(outcome.record)
            if outcome.error is not None and outcome.error.is_terminal:
                finalising = True
                trace.escalation_required = True
            if any(d["flags"] for d in outcome.record.hook_decisions):
                trace.injection_flagged = True
            mark = "✗" if outcome.is_error else "✓"
            say(f"  {mark} {block.name}({json.dumps(block.input)}) -> "
                f"{outcome.record.returned_to_model}")
            results.append({"type": "tool_result", "tool_use_id": block.id,
                            "content": outcome.content, "is_error": outcome.is_error})

        if gate.calls_attempted >= limits.max_tool_calls and not finalising:
            finalising = True           # nothing left to spend; ask for the answer
            trace.limit_reached = trace.limit_reached or "max_tool_calls"
        messages.append({"role": "user", "content": results})

    trace.limit_reached = trace.limit_reached or "max_rounds"
    return finish(None, SentinelFailure(
        FailureKind.TOOL_LIMIT_EXCEEDED,
        f"Investigation exceeded {limits.max_rounds} round-trips without a final answer.",
    ), "stopped: round limit reached before a final answer")
