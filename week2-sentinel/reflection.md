# Week 2 reflection

Week 1 showed that a fluent, self-consistent answer can still be wrong. Week 2
put an application boundary around that behaviour: Claude generates a response,
and Sentinel controls input, structure, validation, failures, configuration, and
observability.

## What changed from Week 1
The Week-1 JSON experiment became an enforced contract. The reasoning shape now
lives in code (`contract.IncidentAnalysis`) as the single source of truth for
both the API schema and the validated Python type, so the two can never drift.
The rules I wrote in prose last week ("don't treat proximity as causation",
"alert time is not start time") became executable Layer-3 support checks.

## What I learned that wasn't in the plan
- **Auth is not one thing.** A Claude *subscription* OAuth token authenticates to
  the Messages API but is gated to `claude-haiku-4-5`; Sonnet/Opus return a 429
  with no rate-limit headers. Diagnosing that from the *absence* of headers was
  the most useful debugging moment of the week.
- **Valid JSON is not a correct answer.** API-enforced structured output
  guarantees shape, not sense. The Layer-3 support check is where an
  unsupported-but-well-formed conclusion is caught — and it is the part no API
  feature can do for me.
- **Heuristic validation cuts both ways.** My overclaiming rule first rejected the
  *correct* cautious phrasing ("no confirmed root cause") as overclaiming. Fixing
  the false positive risked false negatives. Content validation is a safety net,
  not a proof.
- **Convenience can hide the truth.** `messages.parse()` turned a truncation into
  a mystery `ValidationError`; using `messages.create(output_config=...)` exposed
  `stop_reason` so the failure could be classified as `TRUNCATED_OUTPUT`.

## Selected model and configuration — the evidence
- **Model: `claude-haiku-4-5`.** Not a quality choice — a constraint: the
  subscription OAuth credential only reaches Haiku on the direct API (measured:
  Haiku OK, Sonnet 5 and Opus 5 both 429). Haiku proved fully capable for the
  incident-analysis task and kept per-run cost around $0.018.
- **Thinking: direct vs extended (budget) on one difficult case.** Both landed on
  the same cautious conclusion (no leading cause, low confidence, conditional
  rollback, 7 missing-info items). Evidence that more thinking organises reasoning
  but does not invent absent evidence — so direct is the sensible default here,
  with thinking reserved for genuinely harder cases.

## Honest limitation — prompt caching
The caching experiment is built and correct, but caching **did not engage** on the
subscription OAuth path even with a >2048-token stable prefix (cache creation and
cache read both 0). This is recorded, not faked. Demonstrating an actual cache
creation + cache read requires a real API key (console.anthropic.com); the code
would then show it unchanged. See `docs/08-prompt-caching.md`.

## The through-line
The model proposes; the application controls. Every safety property this week —
rejecting truncation, rejecting unsupported content, typing every failure,
enforcing secrets handling, controlling tool execution — is the application
enforcing a boundary the model cannot be relied on to enforce itself.
