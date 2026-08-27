# Section 6 — Model selection and thinking

## Model tiers (from the models overview)

| Model | Context | $/1M in | $/1M out | Notes |
|---|---|---|---|---|
| Haiku 4.5 | 200K | $1 | $5 | fastest/cheapest; what our OAuth token can use |
| Sonnet 5 | 1M | $3 | $15 | balanced (needs an API key here) |
| Opus 5 | 1M | $5 | $25 | most capable (needs an API key here) |

Trade-offs: higher tiers give more capability/quality at higher latency and cost.
Feature support also varies — e.g. the `effort` control and adaptive thinking are
4.6+/Opus-tier; Haiku 4.5 does extended thinking via `budget_tokens`.

## Thinking modes

- **Direct response** — no thinking parameter; the model answers immediately.
- **Extended thinking** — the model reasons in `thinking` blocks first. On Haiku:
  `thinking={"type":"enabled","budget_tokens": N}` (N ≥ 1024, < max_tokens).
- **Adaptive thinking** — `{"type":"adaptive"}`, model decides depth (4.6+/Opus).
- **Effort controls** — `output_config.effort: low..max` (4.6+/Opus-tier).
- **Fast mode** — higher tokens/sec at premium price (Opus 5 / Opus 4.8 only).

## The experiment (INC-104, one difficult case, same model)

Live results, `compare_thinking.py`:

| | DIRECT | THINKING |
|---|---|---|
| thinking blocks present | no | **yes** |
| latency | 55.0s | 49.2s |
| input / output tokens | 2639 / 3261 | 2669 / 3235 |
| estimated cost | $0.0189 | $0.0188 |
| leading_hypothesis | **None** | **None** |
| confidence | **low** | **low** |
| # hypotheses | 5 | 4 |
| # missing_information | 7 | 7 |
| rollback decision | conditional | conditional |

## What it shows

**Both runs reached the same cautious conclusion**: no single confirmed cause,
low confidence, conditional rollback, and the same seven pieces of missing
information. This is the point the curriculum makes:

> More thinking does not create evidence that was absent from the incident.

Thinking here produced a slightly more focused hypothesis set (4 vs 5) at
essentially the same token/latency/cost — but it did **not** invent a leading
cause or raise confidence, because the incident brief genuinely doesn't support
one. If thinking HAD produced a confident single cause, that would be a red flag,
and Layer 3 support validation would catch it.

(Latency/token differences here are within run-to-run noise; a rigorous
benchmark — Week 4 — would average several runs. This is a single-case
comparison, as the exercise asks.)

## Run it

```bash
uv run python -m sentinel.compare_thinking
```
