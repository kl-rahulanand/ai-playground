# Sentinel — project instructions for Claude Code

## Purpose
Sentinel turns an incident report (text and/or a dashboard image) into a
**validated incident analysis** — or an **explicit typed failure**. It never
presents a fluent-but-unsupported answer as a result. Claude generates the
analysis; this application controls input, structure, validation, failures,
configuration, and observability.

## Project structure
```
week2-sentinel/
├── src/sentinel/
│   ├── config.py            # env-based config; ConfigError (typed config failure)
│   ├── client.py            # builds the Anthropic client (API key OR OAuth token)
│   │                        #   + map_api_exception() -> typed failures
│   ├── prompts.py           # SYSTEM_CONTRACT (stable) + large CACHING_SYSTEM_CONTRACT
│   ├── contract.py          # Pydantic IncidentAnalysis = the output schema
│   ├── failures.py          # FailureCategory / FailureKind / SentinelFailure
│   ├── validate.py          # Layer 0 input, 1 parse, 2 schema, 3 support
│   ├── basic_request.py     # Section 1: simplest request
│   ├── structured_analysis.py  # Section 3: structured output + valid/invalid
│   ├── stream_analysis.py   # Section 4: streaming + interrupted-stream rejection
│   ├── failures_demo.py     # every failure category
│   ├── generate_dashboard.py / multimodal.py   # Section 5: image input
│   ├── compare_thinking.py  # Section 6: direct vs thinking
│   ├── token_report.py / metrics.py            # Section 7: tokens + cost
│   ├── prompt_cache.py      # Section 8: caching experiment
│   ├── tool_preview.py      # Section 9: tool_use / tool_result lifecycle
│   ├── investigate.py       # Week 3: bounded tool investigation (custom loop CLI)
│   ├── agent_sdk_investigation.py  # Week 3: same investigation on the Claude Agent SDK
│   └── tools/               # Week 3 tool layer
│       ├── registry.py      #   tool specs (Pydantic input models -> schema) + mocked data
│       ├── policy.py        #   allow-lists, value limits, identities/roles, blocked actions, loop limits
│       ├── guards.py        #   pure checks: allow-list, schema, authz, limits, bounded exec, output
│       ├── hooks.py         #   deterministic pre/post tool hooks (deny destructive; wrap untrusted)
│       └── loop.py          #   the bounded tool-execution loop + trace records
├── tests/                   # offline pytest suite (fake client); security regression cases
├── incidents/               # incident briefs + generated dashboard PNG
├── results/                 # saved run artifacts (JSON records + week3-* traces)
└── docs/                    # Week 2 per-section notes (01..10); Week 3 docs live in ../week3/
```

## Build & test commands
- Install / sync deps:  `uv sync`
- Run any module:       `uv run python -m sentinel.<module>`
- Quick import check:   `uv run python -c "import sentinel.validate"`
- Regenerate dashboard: `uv run python -m sentinel.generate_dashboard`
- Offline test suite:   `uv run pytest -q` (no network; scripted fake client)
- Week 3 investigation: `uv run python -m sentinel.investigate [inc-104] [--role ...]`
- Week 3 on Agent SDK:  `uv run python -m sentinel.agent_sdk_investigation`
Each module also has a runnable `main()` that doubles as a live smoke test.

## Coding conventions
- Python 3.14, managed with `uv`. Standard library + `anthropic`, `pydantic`,
  `python-dotenv`, `matplotlib`.
- The Pydantic `IncidentAnalysis` in `contract.py` is the SINGLE source of truth
  for the output shape. Don't hand-write JSON schemas elsewhere — derive them
  with `contract.strict_schema()`.
- All failures are `SentinelFailure` with a `FailureKind`. Don't raise bare
  strings or return `None` for errors; map SDK exceptions via
  `client.map_api_exception`.
- Never trust a response until it passes all validation layers. A truncated
  (`stop_reason == "max_tokens"`) or interrupted response is a failure, not a
  short answer.
- Tool inputs follow the same rule: the Pydantic model in `tools/registry.py`
  is the single source of truth for both the `input_schema` sent to Claude and
  the validator run on what comes back.
- Security decisions (allow-lists, roles, limits, blocked actions) live ONLY in
  `tools/policy.py` + `tools/hooks.py`. Never put them in prompts or in the
  registry. The model must not be able to see or argue with them.
- Tool results are untrusted data. They are wrapped by `hooks.post_tool_use`
  and never interpreted as instructions by application code.

## Safety boundaries
- **Never commit secrets.** `.env`, `*.key` are gitignored. Credentials come only
  from the environment (`ANTHROPIC_AUTH_TOKEN` or `ANTHROPIC_API_KEY`).
- With an OAuth (subscription) token, only `claude-haiku-4-5` works on the direct
  Messages API; Sonnet/Opus need a real API key.
- Sentinel proposes only **reversible** next actions and never claims a confirmed
  root cause unless the evidence establishes it.
- Do not weaken Layer 3 support rules to make a response pass.
- **No production write capability.** Every tool in `tools/registry.py` is
  read-only over fictional data. `tools/policy.BLOCKED_ACTIONS` names the
  destructive verbs the pre-tool hook refuses; do not add write tools.
- The tool loop must always terminate: `LoopLimits` (max calls, max rounds,
  wall clock, per-tool timeout) are enforced in `tools/loop.py` and are never
  exposed to the model.

## Definition of done
A change is done when:
1. `uv run python -m sentinel.<module>` runs clean from a fresh checkout (after
   `uv sync` and a valid `.env`).
2. New model output flows through `validate_response` (or an equivalent typed
   path) — no unvalidated content is accepted.
3. Any new failure mode has a `FailureKind` and a category.
4. Behaviour is recorded in the matching `docs/NN-*.md`.
