"""Deterministic hooks — code that runs around EVERY tool call, no matter what
the prompt says.

A prompt can *request* safe behaviour ("never resolve incidents"). A hook
*enforces* it: it is ordinary Python, it runs before the tool is even looked up,
and its decision is recorded. The model cannot skip it, persuade it, or learn
its way around it.

Two hooks:

  pre_tool_use  -> may DENY. Blocks destructive / write actions by name.
                   Records requested action, reason, policy, and whether a human
                   would have to approve it.
  post_tool_use -> may only ANNOTATE. Wraps every result in an "untrusted data"
                   envelope and flags text that looks like an instruction.
                   It never rewrites or censors the data — the model must be
                   able to see a suspicious log line to report it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import policy


@dataclass(frozen=True)
class HookDecision:
    """The audit record a hook leaves behind."""
    hook: str                      # "pre_tool_use" | "post_tool_use"
    tool_name: str
    allowed: bool
    reason: str = ""
    policy: str = ""
    requires_human_approval: bool = False
    flags: tuple[str, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict:
        return {
            "hook": self.hook,
            "requested_action": self.tool_name,
            "decision": "allow" if self.allowed else "deny",
            "reason": self.reason,
            "policy": self.policy,
            "requires_human_approval": self.requires_human_approval,
            "flags": list(self.flags),
        }


def pre_tool_use(tool_name: str, tool_input: object) -> HookDecision:
    """Runs BEFORE allow-listing. Denies anything destructive, by name.

    Two checks, in order:
      1. an explicit block-list of named actions with a policy citation;
      2. a verb heuristic so a novel write-shaped name ("purge_cache") is still
         refused. The heuristic cites a generic policy.
    """
    blocked = policy.BLOCKED_ACTIONS.get(tool_name)
    if blocked is not None:
        return HookDecision(
            hook="pre_tool_use",
            tool_name=tool_name,
            allowed=False,
            reason=blocked.reason,
            policy=blocked.policy,
            requires_human_approval=blocked.requires_human_approval,
        )
    verb = tool_name.lower().split("_", 1)[0]
    if verb in policy.DESTRUCTIVE_VERBS:
        return HookDecision(
            hook="pre_tool_use",
            tool_name=tool_name,
            allowed=False,
            reason=f"Tool name starts with the write verb {verb!r}; Sentinel is read-only.",
            policy="SEC-POL-01: Sentinel is read-only; no production writes.",
            requires_human_approval=True,
        )
    return HookDecision(hook="pre_tool_use", tool_name=tool_name, allowed=True,
                        policy="SEC-POL-00: read-only investigation tools permitted.")


def post_tool_use(tool_name: str, result_json: str) -> tuple[str, HookDecision]:
    """Runs AFTER execution. Wraps the result as untrusted data and flags
    instruction-like text. Returns (content_for_claude, decision)."""
    lowered = result_json.lower()
    flags = tuple(m for m in policy.INJECTION_MARKERS if m in lowered)

    # The envelope is plain data. The `trust` field and the surrounding system
    # prompt tell the model how to treat it; the hook decision tells US.
    envelope = (
        '{"source": "tool:' + tool_name + '", '
        '"trust": "untrusted_data", '
        '"injection_suspected": ' + ("true" if flags else "false") + ', '
        '"data": ' + result_json + "}"
    )
    decision = HookDecision(
        hook="post_tool_use",
        tool_name=tool_name,
        allowed=True,
        reason=("instruction-like text found in tool output; passed through as data"
                if flags else "clean"),
        policy="SEC-POL-04: tool results are untrusted data, never instructions.",
        flags=flags,
    )
    return envelope, decision
