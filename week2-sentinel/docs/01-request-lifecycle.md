# Section 1 — The Claude request/response lifecycle

Goal: send INC-104 to Claude and understand every part of the request and the
response before we add validation, streaming, and failure handling.

## The request

`client.messages.create(...)` calls `POST /v1/messages`. The parts that matter:

| Field | What it is | Sentinel's use |
|---|---|---|
| `model` | Which Claude model serves the request | From `.env` (`SENTINEL_MODEL`) |
| `system` | Stable instructions, sent as a top-level field (not a message) | The analytical contract (`SYSTEM_CONTRACT`) |
| `messages` | The conversation turns, alternating user/assistant | One `user` turn: the incident |
| `max_tokens` | **Hard ceiling** on output tokens | `SENTINEL_MAX_TOKENS` |

Render order on the wire is `tools` → `system` → `messages`. That ordering is
why the stable contract goes in `system` and the volatile incident goes in
`messages`: it keeps the cacheable prefix first (used in Section 7).

## The response

`messages.create` returns a `Message`. Key fields:

- **`content`** — a *list* of content blocks, not a string. Each block has a
  `type` (`text`, `thinking`, `tool_use`, ...). You must check `block.type`
  before reading `block.text`. A single response can mix block types.
- **`stop_reason`** — why generation stopped:
  - `end_turn` — finished naturally (the good case)
  - `max_tokens` — **truncated**; the answer is incomplete and must not be trusted
  - `refusal` — the model declined for safety; `stop_details` explains why
  - `tool_use` — the model wants a tool (Section 9)
  - `stop_sequence` — hit a configured stop string
- **`usage`** — token accounting: `input_tokens`, `output_tokens`, and (later)
  `cache_creation_input_tokens` / `cache_read_input_tokens`.
- **`model`** — the exact model string that actually served the request.
- **`_request_id`** — the `request-id` header; log it when reporting a problem
  to Anthropic. (Public despite the underscore.)

## The mental model for the whole week

> Claude generates a response. The **application** controls input, structure,
> validation, failures, configuration, and observability.

Section 1 is only the "generate a response" arrow. Everything after this adds an
application boundary around it.

## Why `max_tokens` is a limit, not a length

`max_tokens` caps how many tokens the model may emit. The model does not aim for
that number — it stops when it's done (`end_turn`) or when it hits the cap
(`max_tokens`). Hitting the cap truncates mid-thought, which is why Sentinel
treats `stop_reason == "max_tokens"` as a failure, not a short answer.

## Run it

```bash
cd week2-sentinel
cp .env.example .env        # then paste your sk-ant-... key into .env
uv run python -m sentinel.basic_request          # INC-104
uv run python -m sentinel.basic_request inc-205  # a second incident
```

Without a key, the app raises a typed `ConfigError` with a fix-it message —
that is the *configuration failure* category, the first of the taxonomy we build
in Section 4.
