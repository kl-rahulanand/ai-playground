# Week 3 — knowledge check

Self-assessment against the learning objectives and completion criteria, each
with where it is demonstrated. Timed: written in one sitting from memory,
then checked against the code.

### 1. Define tools using clear descriptions and JSON schemas
Three `ToolSpec`s in `tools/registry.py`. Each has a narrow name, a description
that states purpose, units and trust level, and an `input_schema` derived from
a Pydantic model (enums for allowed values, patterns for times, min/max for
counts, `additionalProperties: false`). Step 2.

### 2. Implement the `tool_use` / `tool_result` lifecycle
`tools/loop.py`: append the assistant's `tool_use` turn, then one user turn
holding a `tool_result` per `tool_use_id` (all parallel results in one
message), `is_error: true` on failures. Step 1 protocol rules; Step 3.

### 3. Build a bounded tool-execution loop
`run_investigation`: `max_tool_calls`, `max_rounds`, `max_wall_seconds`,
`tool_timeout_seconds`, all in `policy.LoopLimits`, never sent to the model.
Termination argument in Step 3; tests `test_round_limit_*`, `test_wall_clock_*`.

### 4. Validate tool inputs and outputs outside the model
`guards.validate_input` (same Pydantic model as the schema), `guards.enforce_value_limits`
(services, dependencies, windows, sizes), `guards.validate_output` (shape,
counts, bytes, serialisability). Cases 2 and 6.

### 5. Apply authorization and least-privilege controls
`policy.Identity` + `ROLE_PERMISSIONS` (tools, services, budget per role);
`guards.authorize`. Identity supplied by the application. Case 3 live:
contractor executed 0 of 6; observer got metrics, not dependency health.

### 6. Treat tool results as untrusted data
`hooks.post_tool_use` wraps every result `{"trust": "untrusted_data", ...}` and
flags instruction-like text without censoring it; system-prompt rule B tells
the model what the label means. Case 4.

### 7. Prevent prompt injection from changing system authority
The planted log line was delivered, flagged, and ignored in every live run. A
scripted attempt to obey it (`mark_incident_resolved`) is denied by the
pre-hook with policy SEC-POL-03, tools are switched off (`tool_choice: none`),
and `escalation_required` is set. No write tool exists to be granted.
Regression test `test_prompt_injection_in_tool_result_is_data_not_authority`.

### 8. Use hooks for deterministic safety enforcement
`hooks.pre_tool_use` (deny by name/verb, with reason, policy id, human-approval
flag) runs at stage 0 of every call, in both the custom loop and, via
`HookMatcher`, the Agent SDK. Step 5.

### 9. Compare a custom workflow with the Claude Agent SDK
Same investigation built twice with one shared `ToolGate`. Eight-row
comparison and decision in Step 6.

### 10. Explain when to use a workflow, an agent, or a multi-agent design
Decided from traces: Sentinel is a bounded agent; multi-agent designed on
paper (manager + metrics analyst + quarantined logs analyst) and not built
because no measurable benefit over hooks + per-identity policy. Step 7.

### Completion criteria
| Criterion | Evidence |
|---|---|
| Obtains mocked evidence using approved tools | baseline run: 6 executed calls, 8 facts citing tools |
| Malformed and unauthorized requests cannot execute | cases 1-3: execution `not_reached` |
| Tool results treated as untrusted input | envelope on every result; `injection_flagged` in traces |
| Prompt injection cannot grant additional authority | case 4; no write capability; hook denial |
| Tool loop always terminates | three counters + per-tool timeout; tests |
| Failures represented explicitly | `FailureKind.TOOL_*`, `ToolError`, `is_error` results, trace stages |
| No production write capability | `test_every_advertised_tool_is_read_only_and_allow_listed` |
| Architecture supported by evidence | Steps 6 and 7 cite the traces |
