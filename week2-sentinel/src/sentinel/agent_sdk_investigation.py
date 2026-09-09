"""Week 3, Part 6 — the SAME bounded investigation, built on the Claude Agent SDK.

Run it:
    uv run python -m sentinel.agent_sdk_investigation
    uv run python -m sentinel.agent_sdk_investigation inc-104 --role external-contractor

What is different from tools/loop.py:
  * The SDK owns the loop. We never see `stop_reason`, never append messages,
    never send a tool_result. We hand it a prompt, options, and tool handlers.
  * Our tools are exposed as an IN-PROCESS MCP server (`create_sdk_mcp_server`).
    The SDK names them `mcp__sentinel__<tool>`.
  * Deterministic control comes from three SDK features: `tools=[]` (no
    built-in Bash/Read/Write), `allowed_tools=[...]` (only our three), and a
    `PreToolUse` hook (our policy check + our call budget).

What is deliberately the SAME:
  * Every tool handler goes through the identical ToolGate from tools/loop.py:
    hook -> allow-list -> schema -> identity -> limits -> bounded execution ->
    output validation -> untrusted-data envelope. One security implementation,
    two loops. The SDK replaces the escort, not the guard.
  * The final text is still pushed through validate_response (Layers 1-3).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    HookMatcher,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
    create_sdk_mcp_server,
    query,
    tool,
)

from .config import INCIDENTS_DIR, load_settings, read_incident
from .contract import strict_schema
from .failures import FailureKind, SentinelFailure
from .prompts import INVESTIGATION_SYSTEM_PROMPT, build_investigation_message
from .tools import hooks, policy
from .tools.loop import InvestigationTrace, ToolCallRecord, ToolGate
from .tools.registry import TOOL_SPECS
from .validate import validate_input, validate_response

SERVER_NAME = "sentinel"
_PREFIX = f"mcp__{SERVER_NAME}__"


def _bare(name: str) -> str:
    """'mcp__sentinel__search_logs' -> 'search_logs'."""
    return name[len(_PREFIX):] if name.startswith(_PREFIX) else name


def build_server(gate: ToolGate, trace: InvestigationTrace):
    """Wrap each registry tool as an SDK tool whose handler is the ToolGate."""

    def make(name: str):
        spec = TOOL_SPECS[name]

        async def handler(args: dict[str, Any]) -> dict[str, Any]:
            # tool_use_id is not exposed to SDK tool handlers; use a counter.
            tid = f"sdk_{len(trace.tool_calls) + 1}"
            outcome = gate.handle(tid, name, args)
            trace.tool_calls.append(outcome.record)
            if any(d["flags"] for d in outcome.record.hook_decisions):
                trace.injection_flagged = True
            return {"content": [{"type": "text", "text": outcome.content}],
                    "is_error": outcome.is_error}

        # The SDK accepts a full JSON schema dict — the same one the custom
        # loop sends to the Messages API, derived from the Pydantic model.
        return tool(name, spec.description, spec.definition["input_schema"])(handler)

    return create_sdk_mcp_server(
        name=SERVER_NAME, version="1.0.0",
        tools=[make(n) for n in sorted(policy.ALLOWED_TOOLS)],
    )


def build_pre_tool_use_hook(gate: ToolGate, limits: policy.LoopLimits, trace: InvestigationTrace):
    """The deterministic hook. Runs inside the SDK BEFORE any tool executes."""

    async def pre_tool_use(input_data: dict, tool_use_id: str | None, _ctx: Any) -> dict:
        name = _bare(input_data.get("tool_name", ""))

        # 1. Policy: destructive names are denied with an audit record.
        decision = hooks.pre_tool_use(name, input_data.get("tool_input"))
        if not decision.allowed:
            trace.escalation_required = True
            trace.tool_calls.append(ToolCallRecord(
                tool_use_id=tool_use_id or "sdk_hook", requested_action={"tool": name, "input": input_data.get("tool_input")},
                validation="rejected: blocked by policy hook", authorization="not_reached",
                execution="not_reached", returned_to_model="error:tool_blocked_by_policy",
                hook_decisions=[decision.as_dict()]))
            return {"hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": f"{decision.reason} ({decision.policy})",
            }}

        # 2. Budget: the SDK has max_turns but no max-tool-calls; we add it here.
        #    Only OUR evidence tools spend budget. The SDK's internal
        #    `StructuredOutput` tool (how output_format delivers the final
        #    answer) must never be refused, or the agent cannot finish.
        if not input_data.get("tool_name", "").startswith(_PREFIX):
            return {}
        if gate.calls_attempted >= limits.max_tool_calls:
            trace.limit_reached = trace.limit_reached or "max_tool_calls"
            trace.tool_calls.append(ToolCallRecord(
                tool_use_id=tool_use_id or "sdk_hook", requested_action={"tool": name, "input": input_data.get("tool_input")},
                validation="not_evaluated: budget exhausted", authorization="not_evaluated",
                execution="refused", returned_to_model="error:tool_limit_exceeded"))
            return {"hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": (
                    f"Tool-call budget of {limits.max_tool_calls} exhausted; "
                    "answer from the evidence already gathered."),
            }}
        return {}

    return pre_tool_use


async def investigate(incident_text: str, *, model: str, identity: policy.Identity,
                      limits: policy.LoopLimits, log=None):
    say = log or (lambda *_: None)
    perms = policy.permissions_for(identity)
    if perms is not None:
        limits = limits.capped_by(perms)
    trace = InvestigationTrace(identity=identity.__dict__.copy(), limits=limits.__dict__.copy())
    gate = ToolGate(identity, limits)
    server = build_server(gate, trace)

    options = ClaudeAgentOptions(
        model=model,
        system_prompt=INVESTIGATION_SYSTEM_PROMPT,
        mcp_servers={SERVER_NAME: server},
        tools=[],                                    # NO built-in tools at all
        allowed_tools=[_PREFIX + n for n in sorted(policy.ALLOWED_TOOLS)],
        disallowed_tools=["Bash", "Read", "Write", "Edit", "WebSearch", "WebFetch", "Agent"],
        max_turns=limits.max_rounds,                  # the SDK's round limit
        output_format={"type": "json_schema", "schema": strict_schema()},  # same contract as Week 2
        hooks={"PreToolUse": [HookMatcher(hooks=[build_pre_tool_use_hook(gate, limits, trace)])]},
        setting_sources=[],                           # ignore .claude/settings.json etc.
    )

    started = time.monotonic()
    final_text = ""
    result_msg: ResultMessage | None = None
    try:
        async with asyncio.timeout(limits.max_wall_seconds):       # our wall clock
            async for message in query(prompt=build_investigation_message(incident_text),
                                       options=options):
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, ToolUseBlock):
                            if block.name == "StructuredOutput":
                                say("  → Claude submits the final structured answer")
                            else:
                                say(f"  → Claude requests {_bare(block.name)}({json.dumps(block.input)})")
                        elif isinstance(block, TextBlock) and block.text.strip():
                            final_text = block.text
                elif isinstance(message, ResultMessage):
                    result_msg = message
    except TimeoutError:
        trace.limit_reached = "max_wall_seconds"
        trace.elapsed_seconds = round(time.monotonic() - started, 2)
        trace.final_behaviour = "stopped: wall-clock limit reached"
        return None, SentinelFailure(FailureKind.TOOL_LIMIT_EXCEEDED,
                                     f"Agent exceeded {limits.max_wall_seconds:.0f}s."), trace, None

    trace.elapsed_seconds = round(time.monotonic() - started, 2)
    if result_msg is not None:
        trace.rounds.append({"sdk_result": result_msg.subtype, "num_turns": result_msg.num_turns,
                             "cost_usd": result_msg.total_cost_usd, "is_error": result_msg.is_error})
        if result_msg.structured_output is not None:      # API-enforced JSON
            final_text = json.dumps(result_msg.structured_output)
        elif result_msg.result:
            final_text = result_msg.result
        if result_msg.permission_denials:
            trace.rounds.append({"sdk_permission_denials": len(result_msg.permission_denials)})
    if result_msg is not None and result_msg.terminal_reason == "max_turns":
        trace.limit_reached = trace.limit_reached or "max_rounds"
    if result_msg is None or result_msg.is_error:
        trace.final_behaviour = "stopped: SDK reported an error"
        return None, SentinelFailure(FailureKind.API_ERROR, "Agent SDK reported an error.",
                                     detail=str(final_text)[:300]), trace, result_msg
    try:
        analysis = validate_response(final_text, stop_reason="end_turn")
    except SentinelFailure as f:
        trace.final_behaviour = f"stopped: final answer rejected ({f.kind.value})"
        return None, f, trace, result_msg
    trace.final_behaviour = "completed: validated analysis"
    if trace.limit_reached:
        trace.final_behaviour += f" after {trace.limit_reached} limit"
    if trace.escalation_required:
        trace.final_behaviour += "; escalation required (policy hook fired)"
    return analysis, None, trace, result_msg


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("incident", nargs="?", default="inc-104")
    ap.add_argument("--role", default=policy.DEFAULT_IDENTITY.role, choices=sorted(policy.ROLE_PERMISSIONS))
    ap.add_argument("--max-calls", type=int, default=policy.DEFAULT_LIMITS.max_tool_calls)
    args = ap.parse_args(argv)

    settings = load_settings(require_key=False)
    incident = validate_input(read_incident(args.incident))
    identity = policy.Identity(policy.DEFAULT_IDENTITY.name, args.role)
    limits = policy.LoopLimits(max_tool_calls=args.max_calls, max_wall_seconds=240.0)
    print(f"→ Agent SDK  model={settings.model}  incident={args.incident}  role={identity.role}\n")

    analysis, failure, trace, result_msg = asyncio.run(
        investigate(incident, model=settings.model, identity=identity, limits=limits, log=print)
    )
    print(f"\n=== outcome: {trace.final_behaviour} ===")
    print(f"tool calls attempted={len(trace.tool_calls)}  executed={trace.executed_calls}  "
          f"elapsed={trace.elapsed_seconds}s")
    if result_msg is not None:
        print(f"sdk: turns={result_msg.num_turns}  cost_usd={result_msg.total_cost_usd}  "
              f"subtype={result_msg.subtype}")
    for r in trace.tool_calls:
        print(f"  {r.requested_action['tool']}: validation={r.validation} "
              f"authorization={r.authorization} execution={r.execution}")
    if analysis:
        lc = analysis.likely_cause_assessment
        print(f"\nleading_hypothesis : {lc.leading_hypothesis}\nconfidence         : {lc.confidence}"
              f"\nrollback decision  : {analysis.rollback_recommendation.decision}")
    else:
        print(f"\nFAILURE:\n{failure}")

    out = INCIDENTS_DIR.parent / "results" / f"week3-agent-sdk-{args.incident}-{args.role}.json"
    out.write_text(json.dumps({"model": settings.model, "trace": trace.as_dict(),
                               "analysis": analysis.model_dump() if analysis else None,
                               "failure": str(failure) if failure else None}, indent=2))
    print(f"\ntrace saved -> {out.relative_to(INCIDENTS_DIR.parent)}")
    return 0 if analysis else 1


if __name__ == "__main__":
    raise SystemExit(main())
