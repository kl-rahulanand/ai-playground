# Section 7 — Tokens, context, and cost

## The recorded request (`results/token-record.json`)

| Field | Value |
|---|---|
| model | claude-haiku-4-5-20251001 |
| counted input tokens (system+messages only) | 560 |
| **actual input tokens (with schema)** | **2639** |
| schema token overhead | **2079** |
| output tokens | 3151 |
| thinking tokens | n/a here (when enabled on Haiku, counted within output tokens) |
| max output tokens (limit) | 8000 |
| latency | 54.8s |
| stop reason | end_turn |
| estimated cost | **$0.0184** ($0.0026 input + $0.0158 output) |

## Token counting before you send

`client.messages.count_tokens(model, system, messages)` returns the input token
count without generating anything. We counted **560** — but the real request used
**2639** input tokens. The 2079-token gap is the `output_config` JSON Schema,
which `count_tokens` doesn't include but the real request sends. Lesson: count
what you'll actually send; structure has a real input cost.

## The questions the exercise asks

**Why the same prompt tokenizes differently across models.** Each model family
has its own tokenizer. The same text can split into a different number of tokens
on Haiku vs Opus, so token counts (and therefore cost) are model-specific — always
count against the model you'll actually call.

**How context length affects request size.** The API is stateless: every request
resends the full system prompt + all prior messages + tools/schema. Input tokens
grow with the whole context you carry, not just the new user message — a long
conversation gets more expensive each turn because you resend everything.

**Why repeated system instructions consume tokens.** The system prompt is sent on
every request and billed as input every time. A stable 2000-token contract costs
2000 input tokens per call — which is exactly why prompt caching (Section 8)
exists: to stop paying full price for an unchanged prefix.

**Why `max_tokens` is a limit, not a target.** `max_tokens=8000` did not make the
model emit 8000 tokens — it emitted 3151 and stopped naturally (`end_turn`).
`max_tokens` only caps the maximum; hitting it truncates (`stop_reason ==
max_tokens`), which Sentinel treats as a failure.

## Cost model (`metrics.py`)

`cost = input_tokens/1e6 * in_rate + output_tokens/1e6 * out_rate`, with cache
reads/writes billed separately (~0.1x / ~1.25x of the input rate). Haiku 4.5 is
$1/$5 per 1M in/out — output dominates our cost (86% here), because the analysis
is long and the input is small.

## Run it

```bash
uv run python -m sentinel.token_report
```
