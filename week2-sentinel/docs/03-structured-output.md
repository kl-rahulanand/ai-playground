# Section 3 — Structured output and the three validation layers

## Four ways to get JSON, from weakest to strongest

| Approach | What guarantees it | Failure mode |
|---|---|---|
| **A. Ask for JSON in the prompt** | Nothing — a request, not a contract | Model adds ```json fences, prose, or drifts from the shape (we saw this in Section 1) |
| **B. Define a JSON Schema** | A spec you can validate *against* | Doesn't constrain the model by itself; you must still validate |
| **C. API-enforced structured output** (`output_config.format` / `messages.parse`) | The API constrains generation to the schema | Only valid if generation *completes* — a truncation yields incomplete JSON |
| **D. Validate support** | Your own rules | This is where "valid JSON, wrong conclusion" is caught |

Sentinel uses **B feeding C**, then **D** on top.

## The three validation layers (`src/sentinel/validate.py`)

```
raw text ─▶ Layer 1 PARSE  ─▶ Layer 2 SCHEMA ─▶ Layer 3 SUPPORT ─▶ accepted
             MALFORMED         SCHEMA_INVALID     UNSUPPORTED
```

- **Layer 1 — parse.** Is it JSON at all? Strips fences/prose, `json.loads`.
  Failure → `MALFORMED_RESPONSE`.
- **Layer 2 — schema.** Does it match `IncidentAnalysis`? Pydantic.
  Failure → `SCHEMA_INVALID`.
- **Layer 3 — support.** Are the conclusions *earned by the evidence*?
  Failure → `UNSUPPORTED_CONTENT`.

With API-enforced output (C), Layers 1 and 2 are guaranteed by the API — but
**Layer 3 is still entirely ours**. That is the point of the week:

> A response with valid JSON can still contain an unsupported conclusion.

## Layer 3 rules (the reasoning discipline, as code)

Encoded from Week 1's findings:
1. A named `leading_hypothesis` must actually be one of the candidates.
2. `high` confidence requires a leading hypothesis, with supporting evidence and
   no remaining `evidence_needed` (otherwise the case isn't closed).
3. Don't recommend an irreversible `rollback` at `low` confidence or with no
   leading hypothesis.
4. Every hypothesis needs some evidentiary content.
5. A stated *fact* must be an observation, not a causal claim ("X caused Y").
6. No overclaiming language ("confirmed root cause", "proven", "definitely").
7. Uncertainty must actually be stated.

These are heuristics, not proofs — but they catch the precise ways a fluent
answer outruns its evidence.

## The two required examples

- **Valid** (`analyze_structured`, live): Haiku returned `leading_hypothesis:
  null`, `confidence: low`, `rollback: conditional`, 4 competing hypotheses —
  passed all three layers.
- **Invalid** (`INVALID_BUT_WELL_FORMED`, deterministic): valid JSON of the right
  shape, but high confidence with unresolved evidence, a causal "fact", proof
  language, and empty uncertainty → rejected by Layer 3 with 6 issues.

## Run it

```bash
uv run python -m sentinel.structured_analysis          # INC-104
uv run python -m sentinel.structured_analysis inc-205  # a second incident
```
