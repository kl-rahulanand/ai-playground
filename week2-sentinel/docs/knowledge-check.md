# Week 2 — knowledge check

Self-assessment against the completion criteria, with where each is demonstrated.

### 1. Run Sentinel from a clean checkout
`uv sync` + `.env` + `uv run python -m sentinel.<module>`. See README. Config is
env-based (`config.py`); a missing credential raises a typed `ConfigError`.

### 2. Explain the Claude request and response lifecycle
Request = `model` + `system` + `messages` + `max_tokens` (+ `output_config`,
`tools`). Response = `content` (list of typed blocks), `stop_reason`, `usage`,
`model`, `_request_id`. See `docs/01-request-lifecycle.md`.

### 3. Produce and validate structured output
`output_config.format` (schema from `contract.strict_schema()`) enforces the
shape; `validate.py` runs parse → schema → support. Valid and invalid examples in
`structured_analysis.py`. See `docs/03-structured-output.md`.

### 4. Reject malformed and incomplete responses
- Malformed JSON → `MALFORMED_RESPONSE` (Layer 1).
- Wrong shape → `SCHEMA_INVALID` (Layer 2).
- Truncated (`stop_reason == max_tokens`) → `TRUNCATED_OUTPUT`.
- Interrupted stream → partial buffer fails Layer 1 → `INTERRUPTED_STREAM`.
Demonstrated in `stream_analysis.py` and `failures_demo.py`.

### 5. Distinguish API failure from unsafe model content
`FailureCategory`: `input` / `configuration` / `integration` / `runtime` vs
`model_output`. An HTTP-200 response with valid JSON can still be rejected as
`UNSUPPORTED_CONTENT` — that's unsafe content, not an API failure. See
`docs/04-streaming-and-failures.md`.

### 6. Explain basic model and thinking trade-offs
Haiku/Sonnet/Opus differ in capability, latency, cost, and features. Direct vs
extended-thinking measured on one case: both stayed cautious — thinking does not
invent evidence. See `docs/06-model-and-thinking.md`.

### 7. Read token and cache usage
`usage.input_tokens` / `output_tokens` / `cache_creation_input_tokens` /
`cache_read_input_tokens`, plus `count_tokens` before sending. Recorded in
`results/token-record.json`. See `docs/07-tokens-and-cost.md`.

### 8. Estimate basic request cost
`metrics.estimate_cost` uses the per-model rate table; one INC-104 analysis on
Haiku ≈ $0.018 (output-dominated). See `docs/07-tokens-and-cost.md`.

### 9. Explain prompt caching without confusing it with memory
See `docs/08-prompt-caching.md`: prompt caching (server-side reuse of an
unchanged token PREFIX) ≠ KV cache (in-attention key/values for one forward pass)
≠ conversation history (messages you resend) ≠ application memory (state your app
persists).

### 10. Configure Claude Code for the repository
`CLAUDE.md`, `.claude/settings.json`, and `/analyze-incident` command. Clean vs
continued sessions, config inspection, and why `CLAUDE.md` isn't a security
boundary — `docs/09-claude-code.md`.

### 11. Explain that Claude requests tools while application code controls execution
`tool_preview.py` walks one `tool_use` → validate → execute → `tool_result` →
continue exchange. Claude only *asks*; the application validates and runs. See
`docs/10-tool-use.md`.

## Required exercises — status

| # | Exercise | Status |
|---|---|---|
| 1 | Streaming and non-streaming | ✅ `stream_analysis.py` |
| 2 | Reject an interrupted stream | ✅ partial → `INTERRUPTED_STREAM` |
| 3 | One valid and one invalid structured response | ✅ `structured_analysis.py` |
| 4 | One fictional dashboard image | ✅ `generate_dashboard.py` + `multimodal.py` |
| 5 | Classify failures (5 categories) | ✅ `failures_demo.py` |
| 6 | Direct vs thinking | ✅ `compare_thinking.py` |
| 7 | Record tokens, latency, stop reason, cost | ✅ `results/token-record.json` |
| 8 | Prompt-caching experiment | ✅ `prompt_cache.py` (see doc for result) |
| 9 | CLAUDE.md + project settings | ✅ `CLAUDE.md`, `.claude/settings.json` |
| 10 | One reusable command | ✅ `/analyze-incident` |
| 11 | Annotate tool_use / tool_result | ✅ `tool_preview.py` + `docs/10-tool-use.md` |
