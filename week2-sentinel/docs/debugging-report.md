# Sentinel — Week 2 debugging report

Real problems hit while building, and how each was classified and fixed. Every
one maps to a failure category from the taxonomy (`src/sentinel/failures.py`).

## 1. OAuth token rejected — `401 Invalid bearer token`
- **Category:** configuration (auth)
- **Symptom:** `anthropic.AuthenticationError: 401 ... Invalid bearer token`. The
  masked token started with `AqvLHnAX...` (92 chars) — not the `sk-ant-oat01-...`
  shape a real token has.
- **Cause:** the value pasted into `.env` was the intermediate OAuth
  *authorization code*, not the token that `claude setup-token` prints at the end.
- **Fix:** paste the final `sk-ant-oat01-...` token. Auth then succeeded.

## 2. Premium models blocked on the OAuth path — `429 rate_limit_error`
- **Category:** integration (rate limit) — but really an access gate.
- **Symptom:** `429` with **no** standard `anthropic-ratelimit-*` headers and a
  terse `"message":"Error"`. Persisted across SDK retries.
- **Diagnosis:** tested each tier with `max_retries=0`:
  `claude-haiku-4-5` → OK; `claude-sonnet-5` → 429; `claude-opus-5` → 429.
- **Cause:** a Claude **subscription** OAuth token is gated to Haiku on the direct
  Messages API. This is not normal per-org API quota (hence the missing headers).
- **Fix:** default `SENTINEL_MODEL=claude-haiku-4-5` for the OAuth path; document
  that a real API key is needed for Sonnet/Opus.

## 3. `.env` silently overrode the model default
- **Category:** configuration
- **Symptom:** after setting the code default to Haiku, runs still showed
  `model=claude-opus-5`.
- **Cause:** the `.env` (copied from an earlier template) already had
  `SENTINEL_MODEL=claude-opus-5` on line 22. `.env` wins over code defaults.
- **Fix:** correct the line in `.env`. Lesson: environment beats defaults —
  always check the actual resolved value, not the code default.

## 4. Structured output truncated, but surfaced as a mystery parse error
- **Category:** model_output (truncated) — misclassified as integration at first.
- **Symptom:** `messages.parse()` raised
  `ValidationError: Invalid JSON: EOF while parsing ... column 18568`.
- **Cause:** `max_tokens=4000` cut the JSON off mid-string. `messages.parse()`
  parses internally and raised before we could read `stop_reason`, so the real
  cause (truncation) was hidden.
- **Fix:** switch to `messages.create(output_config=...)` so we get the raw text
  **and** `stop_reason`; our `validate_response()` checks `stop_reason ==
  "max_tokens"` first and returns a clean `TRUNCATED_OUTPUT`. Also raised
  `SENTINEL_MAX_TOKENS` to 8000. Lesson: convenience wrappers can hide the
  metadata you need to classify a failure.

## 5. Strict schema rejected — `400 additionalProperties must be false`
- **Category:** integration (bad request) → fixed in our schema generation.
- **Symptom:** `400 ... output_config.format.schema: For 'object' type,
  'additionalProperties' must be explicitly set to false`.
- **Cause:** Pydantic's `model_json_schema()` omits `additionalProperties: false`
  and doesn't force every property into `required`. `messages.parse()` adds these
  internally; the raw `output_config` path does not.
- **Fix:** `contract.strict_schema()` walks the schema and sets
  `additionalProperties=false` + `required=all` on every object (including
  `$defs`).

## 6. Input tokens tripled with structured output (observation, not a bug)
- **Observation:** prompt-only request = 560 input tokens; structured-output
  request = 2639 input tokens for the same incident.
- **Cause:** the JSON Schema is part of the request and is tokenized as input.
- **Takeaway:** enforcing structure has a real input-token cost — relevant to the
  cost section and to prompt caching (a stable schema is a good caching candidate).
