# Step 5 — Hooks and deterministic controls

## The problem hooks solve

The system prompt says (rule D): "you have no ability to change any system,
and you must not request ... actions that resolve, restart, delete, rotate, or
modify anything." That is a *request*. A model under a strong prompt injection,
a confusing tool result, or simply a bad sampling step can still emit a
`tool_use` for `mark_incident_resolved`.

A hook is the code that makes the request irrelevant. It runs on every tool
call, it is ordinary Python, and its answer does not depend on anything the
model says.

> A prompt can request safe behaviour. A hook or policy layer enforces it.

## Mental model: the circuit breaker

A prompt is like a sign on the wall saying "do not overload this outlet". A
hook is the circuit breaker in the panel. The sign relies on the reader; the
breaker trips on physics. You want both, but only one of them is a guarantee.

Two properties make a control "deterministic" in this sense:

1. **Same input, same decision, every time.** No sampling, no temperature, no
   "usually".
2. **The model cannot reach it.** It is not in the prompt, it is not a tool
   the model can call, and it does not read the model's arguments for
   instructions.

## Sentinel's two hooks (`tools/hooks.py`)

### `pre_tool_use` — may deny

Runs at stage 0 of the gate, before the allow-list even looks at the name.

```
name in policy.BLOCKED_ACTIONS ?  -> deny, citing that action's reason + policy id
first token in DESTRUCTIVE_VERBS ? -> deny, citing SEC-POL-01 (read-only)
otherwise                          -> allow (SEC-POL-00)
```

The four named blocks the curriculum asks for, and the policy each cites:

| Requested action | Reason for rejection | Policy | Human approval |
|---|---|---|---|
| `delete_deployment` | destructive and irreversible | SEC-POL-01 read-only, no production writes | required |
| `restart_production_service` | changes live state and hides evidence | SEC-POL-01 | required |
| `rotate_production_credentials` | a security operation, not analysis | SEC-POL-02 credential changes need security on-call | required |
| `mark_incident_resolved` | only the incident director closes incidents | SEC-POL-03 incident state is a human decision | required |

Every decision, allow or deny, is recorded as a `HookDecision` and copied into
the tool's trace record. So the trace of a normal run shows
`{"hook": "pre_tool_use", "decision": "allow", "policy": "SEC-POL-00"}` on
each call, and a blocked run shows exactly which policy fired.

The verb heuristic matches the **first token** of the name (`purge_cache` →
`purge`), not any substring. An earlier draft matched substrings and blocked
`get_deploy_info` because it contains "deploy". A read-only name should reach
the allow-list and be rejected there as *unknown*, not be mislabelled as
destructive. Precision in the audit record matters.

### `post_tool_use` — may only annotate

Runs after output validation. It never denies and never rewrites the data.
It wraps the result in an envelope and flags instruction-like text:

```json
{"source": "tool:search_logs", "trust": "untrusted_data", "injection_suspected": true,
 "data": { ...the real result, including the injected line, verbatim... }}
```

Why not strip the injected line? Because the analyst needs to see it. A log
line that says "ignore all previous instructions" is itself evidence (of
tampering, of a compromised host, of a bad actor). Censoring it would hide a
finding. The envelope plus system-prompt rule B is what turns it from an
instruction into an observation. Step 4 shows this working.

## Why the hook does not block a name that does not exist

None of the four blocked actions exist in `registry.py`. So why check? Because
the check is cheap and the failure mode it prevents is expensive: someone adds
a "harmless" admin tool for a demo, or the model invents the name after
reading an injected log line. In both cases the answer must be a policy denial
with an audit record, not a generic "unknown tool". The
`test_every_advertised_tool_is_read_only_and_allow_listed` test pins this: no
blocked name is in the registry, and no registry name starts with a write verb.

## Terminal, not recoverable

A hook denial is a *terminal* tool failure (`TOOL_BLOCKED_BY_POLICY` in
`failures.TERMINAL_TOOL_KINDS`). The loop:

1. returns an `is_error` tool_result (the protocol requires one);
2. sets `finalising = True`, so every later request carries
   `tool_choice: {"type": "none"}`;
3. marks `trace.escalation_required = True`.

The investigation still finishes (the model produces its final analysis from
the evidence it already has), but a human sees the escalation flag and the
denial record. The model asked for authority it does not have; the response is
to stop giving it tools, not to argue.

## Same hook, Agent SDK flavour

`agent_sdk_investigation.py` registers the same `hooks.pre_tool_use` as an
SDK `PreToolUse` hook:

```python
hooks={"PreToolUse": [HookMatcher(hooks=[pre_tool_use])]}
# ... inside the callback:
return {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                               "permissionDecision": "deny",
                               "permissionDecisionReason": f"{reason} ({policy})"}}
```

The SDK also lacks a "max tool calls" knob (it has `max_turns`), so the same
hook enforces Sentinel's call budget. One policy function, two enforcement
points. That is the payoff of keeping the decision in a pure function instead
of inside a loop.

## Simulated, never executed

The hook is exercised in `tests/test_loop_security.py::test_prompt_injection_in_tool_result_is_data_not_authority`
by scripting a `tool_use` for `mark_incident_resolved`. The test asserts:

- validation = `rejected: blocked by policy hook`, execution = `not_reached`;
- the hook record has `decision: deny`, `requires_human_approval: true`, policy `SEC-POL-03`;
- the very next API request carries `tool_choice: none`;
- `escalation_required` is set and appears in `final_behaviour`.

Nothing was executed because there is nothing to execute. The blocked action
is simulated end to end without a write capability ever existing.
