# Sentinel — Week 2

A Claude-powered incident-analysis application. It takes an incident (text and/or
a dashboard image) and produces a **validated incident analysis** or an
**explicit typed failure** — never a fluent-but-unsupported answer.

> Week 1 showed that a convincing response can still be unsafe. Week 2 puts an
> application boundary around that: **Claude generates a response; the application
> controls input, structure, validation, failures, configuration, and
> observability.**

## The flow

```
Incident text or dashboard image
        ↓  validate_input (Layer 0)          -> INVALID_INPUT
Validated application input
        ↓  Messages API (client.py)          -> AUTH / RATE_LIMIT / TIMEOUT / ...
Streamed or complete response
        ↓  parse (Layer 1)                   -> MALFORMED_RESPONSE
        ↓  schema (Layer 2)                  -> SCHEMA_INVALID
        ↓  support (Layer 3)                 -> UNSUPPORTED_CONTENT
Accepted analysis   OR   typed failure
        ↓
Model, prompt, token, latency, cache metadata
```

## Setup (from a clean checkout)

```bash
cd week2-sentinel
uv sync                       # install deps into .venv
cp .env.example .env          # then set ONE credential (see below)
```

Set a credential in `.env`:
- **OAuth (subscription, no API credit):** run `claude setup-token`, paste the
  `sk-ant-oat01-...` into `ANTHROPIC_AUTH_TOKEN`. Works with `claude-haiku-4-5`.
- **API key:** put an `sk-ant-...` from console.anthropic.com into
  `ANTHROPIC_API_KEY`. Lets you set `SENTINEL_MODEL=claude-opus-5` / `-sonnet-5`.

`.env` and `*.key` are gitignored — never commit secrets.

## Run each section

```bash
uv run python -m sentinel.basic_request            # 1. basic request
uv run python -m sentinel.structured_analysis      # 3. structured output (valid + invalid)
uv run python -m sentinel.stream_analysis          # 4. streaming + interrupted-stream rejection
uv run python -m sentinel.failures_demo --live     # 5. every failure category
uv run python -m sentinel.generate_dashboard       #    (make the dashboard PNG)
uv run python -m sentinel.multimodal               # 4/5. text + image
uv run python -m sentinel.compare_thinking         # 6. direct vs thinking
uv run python -m sentinel.token_report             # 7. tokens + latency + cost record
uv run python -m sentinel.prompt_cache             # 8. prompt-caching experiment
uv run python -m sentinel.tool_preview             # 9. tool_use / tool_result lifecycle
```

## Docs (one per section)

| Doc | Topic |
|---|---|
| `docs/01-request-lifecycle.md` | request/response anatomy |
| `docs/03-structured-output.md` | four JSON approaches, three validation layers |
| `docs/04-streaming-and-failures.md` | streaming, interruption, failure taxonomy |
| `docs/05-multimodal.md` | text + image, source attribution |
| `docs/06-model-and-thinking.md` | model tiers, direct vs thinking |
| `docs/07-tokens-and-cost.md` | token counting, cost, context |
| `docs/08-prompt-caching.md` | prompt caching vs KV cache vs history vs memory |
| `docs/09-claude-code.md` | CLAUDE.md, settings, commands, sessions |
| `docs/10-tool-use.md` | tool_use/tool_result lifecycle |
| `docs/debugging-report.md` | real bugs hit and how each was classified |
| `docs/knowledge-check.md` | Week 2 completion self-check |

## Key modules

- `contract.py` — `IncidentAnalysis` Pydantic model = the single source of truth
  for the output schema (`strict_schema()` derives the API schema).
- `validate.py` — the four validation layers.
- `failures.py` — typed failure taxonomy (`FailureCategory` / `FailureKind`).
- `client.py` — client construction (both credential types) + SDK-exception → typed-failure mapping.
- `metrics.py` — pricing table, cost estimation, latency timer.
