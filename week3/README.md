# Week 3 — Tools, security, hooks and agent workflows

Week 2 gave Sentinel a controlled Claude call that could only reason from the
incident brief. Week 3 lets Sentinel **investigate**: it can ask for mocked
operational evidence through tools, but every request passes through
application code that validates it, authorizes it, bounds it, executes it under
a deadline, and treats whatever comes back as untrusted data.

> **Key takeaway.** Model intelligence can decide which evidence may be useful,
> but it must never grant itself authority. Validation, permissions, execution
> limits and safety policies belong to the application.

The code lives in `../week2-sentinel/` (Sentinel is one project; Week 3
extends it, it does not fork it). The write-up lives here. Read the steps in
order; each one builds on the previous.

## The steps

| Step | Doc | What you learn | Where the code is |
|---|---|---|---|
| 1 | [01-tool-lifecycle.md](01-tool-lifecycle.md) | Who decides what. The wire protocol. The vending-machine / guard / escort model. | `tools/__init__.py` |
| 2 | [02-tool-definitions.md](02-tool-definitions.md) | Defining three read-only tools. One Pydantic model → schema for Claude + validator for us. Mocked data shaped to discriminate hypotheses. | `tools/registry.py` |
| 3 | [03-execution-loop.md](03-execution-loop.md) | The bounded loop. Three counters the model cannot see. Recoverable vs terminal failures. Why termination is guaranteed. | `tools/loop.py`, `tools/guards.py`, `investigate.py` |
| 4 | [04-security-cases.md](04-security-cases.md) | Seven attack/failure cases with the record each one produced. Prompt injection as data. | `tests/`, `results/week3-*.json` |
| 5 | [05-hooks.md](05-hooks.md) | Deterministic controls. A prompt requests, a hook enforces. The circuit-breaker model. | `tools/hooks.py`, `tools/policy.py` |
| 6 | [06-custom-loop-vs-agent-sdk.md](06-custom-loop-vs-agent-sdk.md) | The same investigation on the Claude Agent SDK. Eight-row comparison and a decision. | `agent_sdk_investigation.py` |
| 7 | [07-workflow-vs-agent.md](07-workflow-vs-agent.md) | Workflow vs agent vs multi-agent, decided from Sentinel's own traces. A manager/subagent design on paper. | — |
| — | [reflection.md](reflection.md) | The short reflection. | — |
| — | [knowledge-check.md](knowledge-check.md) | Completion criteria, each mapped to evidence. | — |

## The request flow (architecture)

```
                         Incident brief (INC-104)
                                  │
                                  ▼  validate_input (Week 2, Layer 0)
        ┌───────────────────────────────────────────────────────────────────┐
        │              run_investigation()  —  tools/loop.py                 │
        │                                                                    │
        │   counters (model cannot see):  max_tool_calls · max_rounds ·      │
        │                                 max_wall_seconds · tool_timeout    │
        │                                                                    │
        │   ┌─► Messages API  (system + tools + structured output)           │
        │   │        │                                                       │
        │   │        ├── stop_reason = tool_use ───► for each tool_use:      │
        │   │        │                                                       │
        │   │        │      ToolGate.handle()                                │
        │   │        │      0 pre_tool_use hook   deny destructive names     │
        │   │        │      1 allow-list          policy.ALLOWED_TOOLS       │
        │   │        │      2 schema              Pydantic input model       │
        │   │        │      3 value limits        services/windows/sizes     │
        │   │        │      4 authorize           identity → role → perms    │
        │   │        │      5 execute_bounded     deadline; mocked data      │
        │   │        │      6 validate_output     shape + byte limit         │
        │   │        │      7 post_tool_use hook  untrusted envelope + flag  │
        │   │        │                 │                                     │
        │   │        │                 ▼  tool_result (is_error if failed)   │
        │   └────────┴──── append; continue  (tool_choice=none once a        │
        │                                     terminal limit is hit)         │
        │            └── stop_reason = end_turn ──► final JSON text          │
        └───────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼  parse → schema → support (Week 2, Layers 1-3)
                    IncidentAnalysis  OR  SentinelFailure
                                  +
                    InvestigationTrace  (every request, every decision)
```

The Agent SDK variant (Step 6) replaces only the outer box: the SDK runs the
loop, and `ToolGate.handle()` plus the same hook are plugged into it unchanged.

## What was added to the Sentinel code

```
week2-sentinel/
├── src/sentinel/
│   ├── failures.py            + FailureCategory.TOOL, seven TOOL_* kinds, ToolError,
│   │                            RECOVERABLE / TERMINAL sets
│   ├── prompts.py             + TOOL_INVESTIGATION_ADDENDUM (rules A-E), investigation prompt
│   ├── investigate.py         NEW  CLI for the custom loop; writes results/week3-*.json
│   ├── agent_sdk_investigation.py  NEW  same investigation on the Claude Agent SDK
│   └── tools/                 NEW
│       ├── registry.py        tool specs (Pydantic → schema), mocked data, executors
│       ├── policy.py          allow-lists, value limits, identities/roles, blocked actions, LoopLimits
│       ├── guards.py          pure checks: allow-list, schema, authz, limits, bounded exec, output
│       ├── hooks.py           pre_tool_use (deny) / post_tool_use (wrap + flag)
│       └── loop.py            ToolGate, run_investigation, trace records
├── tests/                     NEW  39 offline tests (fake client): guards, hooks, all 7 security cases,
│                                   termination guarantees
└── results/week3-*.json       traces of every live run
```

Nothing from Week 2 was removed or duplicated. The output contract, the three
validation layers, the client, the config and the failure taxonomy are reused.

## Run it

```bash
cd week2-sentinel
uv sync                                   # installs pytest + claude-agent-sdk too
uv run pytest -q                          # 39 offline tests, no network
uv run python -m sentinel.investigate     # live: custom loop, on-call engineer
uv run python -m sentinel.investigate inc-104 --role external-contractor
uv run python -m sentinel.investigate inc-104 --fault search_logs=timeout
uv run python -m sentinel.investigate inc-104 --max-calls 2
uv run python -m sentinel.agent_sdk_investigation   # live: Agent SDK
```

Credentials are unchanged from Week 2 (`.env` with `ANTHROPIC_AUTH_TOKEN` or
`ANTHROPIC_API_KEY`; the subscription token reaches `claude-haiku-4-5` only).

## Completion criteria, at a glance

| Criterion | Where shown |
|---|---|
| Sentinel obtains mocked evidence using approved tools | Step 3 live run; `results/week3-inc-104-on-call-engineer.json` |
| Malformed and unauthorized requests cannot execute | Step 4 cases 1-3; `tests/test_loop_security.py` |
| Tool results are treated as untrusted input | Step 4 case 4; `hooks.post_tool_use` envelope |
| Prompt injection cannot grant additional authority | Step 4 case 4 + Step 5; `mark_incident_resolved` denied |
| The tool loop always terminates | Step 3 termination proof; `test_round_limit_*`, `test_wall_clock_*` |
| Failures are represented explicitly | `FailureKind.TOOL_*`, `is_error` tool_results, trace records |
| No production write capability exists | `test_every_advertised_tool_is_read_only_and_allow_listed` |
| The selected architecture is supported by evidence | Steps 6 and 7 (decisions grounded in traces) |
