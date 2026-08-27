---
description: Run Sentinel's validated analysis on an incident and report the outcome
argument-hint: <incident-name, e.g. inc-104>
---

Run Sentinel's structured analysis on incident `$ARGUMENTS` (default to `inc-104`
if no argument was given) and report the result the way Sentinel itself would.

Steps:
1. Confirm the incident file exists: `week2-sentinel/incidents/$ARGUMENTS.md`.
   If it does not, list the available incidents in `week2-sentinel/incidents/`
   and stop.
2. Run: `uv run python -m sentinel.structured_analysis $ARGUMENTS`
   (from the `week2-sentinel/` directory).
3. Report:
   - Whether the analysis was ACCEPTED or REJECTED, and if rejected, the typed
     failure category/kind and the specific issues.
   - For an accepted analysis: the leading hypothesis (or "none"), the confidence,
     the rollback decision, and the count of competing hypotheses and
     missing-information items.
   - The input/output token counts.
4. Do NOT paraphrase the model's conclusion as more certain than it is. If the
   analysis says low confidence / no leading cause, say exactly that.

Remember the project rule: a response is only trustworthy after it passes all
validation layers. Never present unvalidated or truncated output as a result.
