# Step 7 — Workflow, agent, or multi-agent?

## Definitions, as used here

- **Workflow**: the application decides the sequence of steps in advance. The
  model fills in content at fixed points. Branching is limited and known.
- **Agent**: the model decides the next step based on what the previous step
  revealed. The application bounds and validates, but does not script.
- **Multi-agent**: several agents with distinct roles, contexts or
  permissions, coordinated by a manager.

## Mental model: a recipe, a detective, a police department

A workflow is a recipe. Every step is written down; the cook adds skill but
not structure. An agent is a detective: the next interview depends on what the
last witness said, and you cannot write the interview order before you start.
A multi-agent system is a department: detectives, forensics and a captain,
each with their own desk, files and clearance. You build a department when the
case needs specialists who must not share a desk, not because one detective
is busy.

## Evidence from Sentinel's own runs

Read the traces in `week2-sentinel/results/week3-*.json` and ask: could the
sequence have been scripted in advance?

| Run | What the model chose | Could a script have chosen it? |
|---|---|---|
| on-call engineer, custom loop | 5 parallel calls first (2 metrics, 2 dependencies, 1 log search), then a targeted log search for `deployment dep-1842`, then 3 more it was refused | The first batch, yes. The second search was a reaction to reading the first results. |
| on-call engineer, Agent SDK | 4 metrics, 2 dependencies, then 3 log searches for `error`, `timeout`, `credential` | The `credential` search came from the brief's "previous incident involved an expired credential". A script would need to encode that mapping. |
| read-only observer | 2 metrics, then attempted dependency health (denied) | A script would never *attempt* a denied call. The attempt itself is information: the model wanted evidence the role could not supply. |

The second and third rows are the tell. The valuable calls were reactions to
discovered evidence. INC-104 has three live hypotheses and the brief cannot
discriminate between them; the tool calls that help are the ones chosen after
seeing which hypothesis the first results weaken.

## Decision: Sentinel is a bounded agent

Sentinel matches the "agent" criteria the curriculum lists:

- the next step depends on discovered evidence (yes, shown above);
- multiple tool calls may be required (6 to 9 per run);
- the model must choose between valid investigation paths (metrics-first vs
  logs-first are both defensible);
- the workflow cannot be fully determined in advance (which hypothesis to
  chase depends on the data).

It does **not** match the "workflow" criteria: the sequence is not known, and
the branching is not limited.

But "agent" here is heavily qualified. The model chooses *which* read-only
evidence to ask for. The application chooses everything else: allow-list,
schemas, identity, limits, termination, output validation, blocked actions.
The traces show the model refused three times per run by a counter it cannot
see. This is an agent in the sense that the path is discovered, and a workflow
in the sense that the envelope is fixed. The honest label is **bounded agent**.

### What would turn it back into a workflow

If a future incident class turned out to always need the same three calls in
the same order (say: metrics, then dependency, then logs for the top error),
the right move is to script those three calls in code, run them *before* the
model sees anything, and hand the model the evidence pack. Cheaper, faster,
deterministic. Watch the traces: if the model's call pattern stops varying
across incidents, promote it to a workflow.

## Multi-agent: designed on paper, not built

### Proposed architecture

```
                     ┌──────────────────────┐
   incident ───────► │  Manager (Sentinel)  │ ───────► validated analysis
                     │  read-only, no tools │
                     └──────┬───────┬───────┘
          delegates bounded │       │ delegates bounded
          questions         │       │ questions
                    ┌───────▼──┐ ┌──▼────────────┐
                    │ Metrics  │ │ Logs analyst  │
                    │ analyst  │ │ (quarantined) │
                    │ tools:   │ │ tools:        │
                    │ metrics, │ │ search_logs   │
                    │ deps     │ │ only          │
                    └──────────┘ └───────────────┘
                     returns structured findings, never raw tool output
```

- **Manager**: holds the incident and the Week 2 reasoning discipline. Has *no*
  tools. Asks each subagent a specific question ("did error_rate change before
  or after 10:01?") and receives a small structured answer.
- **Metrics analyst**: permitted `get_service_metrics` and
  `get_dependency_health`. Own budget (say 4 calls).
- **Logs analyst**: permitted `search_logs` only, on a separate context. This
  is the one real argument for the split: raw log text is the injection
  surface. If the logs analyst is compromised by an injected line, the damage
  is confined to a context that has no other tools and whose output is a
  schema-validated finding, not free text. The manager never sees the raw
  line, only "one log line at 10:05 contains instruction-like text".

### Why it is not built

The curriculum's bar: "use only when separate roles, contexts or permissions
provide **measurable** value." Measured against the traces:

| Claimed benefit | What the single-agent traces show |
|---|---|
| Injection containment | The injected line was flagged by the post-hook, passed as data, and changed nothing. Containment already exists at the hook layer. |
| Least privilege per role | Already enforced per identity in `policy.py`; a subagent per tool would add a second permission system to keep consistent with the first. |
| Parallelism | The single agent already issues 5 calls in one turn; the API parallelises them. |
| Context size | Whole runs are ~17k input tokens. Nowhere near a limit. |
| Cost | A manager plus two subagents is at least three model contexts per incident. Current cost is ~$0.02-0.05 per run. |

The one benefit that is real (a quarantined context for raw logs) is
currently a defence in depth against a threat the hook already handles.
The trigger to build it would be evidence that the hook is insufficient: an
injected line that measurably changed a conclusion in a regression run. Until
that test fails, the multi-agent design stays on paper.

## Summary

| Question | Answer | Evidence |
|---|---|---|
| Workflow or agent? | Bounded agent | Tool sequences vary and react to results (traces) |
| Multi-agent? | Not now | No measurable gain over hooks + per-identity policy; cost triples |
| When to revisit? | Call patterns stop varying (→ workflow) or an injection regression fails (→ quarantined logs subagent) | Keep the tests and traces running |
