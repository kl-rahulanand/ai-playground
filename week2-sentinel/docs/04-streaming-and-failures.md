# Section 4 — Streaming, interruption, and the failure taxonomy

## Non-streaming vs streaming

- **Non-streaming** (`messages.create`): one HTTP response with the whole answer.
  Simple, but a long generation can hit an HTTP timeout before it returns.
- **Streaming** (`messages.stream`): tokens arrive as server-sent events; you read
  `stream.text_stream` and call `stream.get_final_message()` at the end for the
  usage/stop_reason. Preferred for long or high-`max_tokens` outputs.

Both run the SAME validator afterward — streaming changes *delivery*, not the
acceptance rules.

## Rejecting an interrupted stream (the key exercise)

`run_streaming(..., interrupt_after_chars=400)` stops reading partway through to
simulate a dropped connection / Ctrl-C. We then feed **only the partial buffer**
to `validate_response()`:

```
Stream interrupted after 426 chars
  -> partial text is truncated JSON
  -> Layer 1 (parse) fails: "Response was not valid JSON"
  -> raised as [runtime/interrupted_stream]
```

The proof: partial content can never pass Layer 1, because a half-written JSON
object won't parse. A streamed answer is only accepted after a clean terminal
event **and** all three validation layers. `stop_reason` is `None` on an
interrupted stream — we never received a terminal event — which is itself a
signal the response is incomplete.

## The failure taxonomy (Exercise 5)

Five categories, one source of truth (`failures._CATEGORY`):

| Category | Kinds | Meaning |
|---|---|---|
| `input` | `invalid_input` | The incident we were given is unusable |
| `configuration` | `config_error`, `auth_error` | Our own setup is wrong (missing/bad credential) |
| `integration` | `rate_limit`, `timeout`, `context_limit`, `api_error` | The API call itself failed |
| `runtime` | `interrupted_stream` | Something broke mid-processing |
| `model_output` | `malformed_response`, `schema_invalid`, `unsupported_content`, `truncated_output`, `refusal` | The call succeeded but the CONTENT is unusable |

The critical distinction the curriculum draws:

> Distinguish an **API failure** (integration/configuration — the request didn't
> work) from **unsafe model content** (model_output — the request worked, but the
> answer must not be trusted).

`unsupported_content` is the sharpest example: HTTP 200, valid JSON, correct
shape — and still rejected, because the conclusions aren't supported.

## What's deterministic vs environment-dependent

`failures_demo.py` triggers input, configuration, and all model_output kinds
offline (no API), plus auth + truncation live with `--live`. `rate_limit` we
observed directly (Sonnet/Opus on the OAuth token, see the debugging report);
`timeout` and `context_limit` are classified by `map_api_exception` but are
awkward to force on demand, so they're documented rather than staged.

## A caveat we hit: heuristic content validation is imperfect

Layer 3's "overclaiming language" rule first produced **false positives** — it
flagged cautious phrases like "no *confirmed root cause*" and "not *proven*"
because it matched the words ignoring negation. Making it negation-aware fixed
those but can still miss an assertion sitting right after an unrelated negation.
This is the honest limit of heuristic support-checking: it catches the obvious
overclaims Week 1 identified, but it is a safety net, not a proof of correctness.

## Run it

```bash
uv run python -m sentinel.stream_analysis          # non-stream, stream, interrupted
uv run python -m sentinel.failures_demo --live     # every failure category
```
