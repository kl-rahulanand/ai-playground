# Step 1 — The tool lifecycle: who decides what

## The one-sentence version

Claude can **ask** for a tool. Only the application can **run** one.

## Mental model: the vending machine, the guard, and the escort

Picture three things in a lobby.

- **The vending machine** (`tools/registry.py`) dispenses fictional goods:
  metrics, dependency health, log lines. It has no idea who is standing in
  front of it and does no security checks. It only knows how to look things up.
- **The security guard** (`tools/policy.py` + `tools/guards.py` +
  `tools/hooks.py`) stands between the lobby and the machine. Every request
  passes through the guard: is this a real product? is the request well-formed?
  is this person allowed? is the request within limits? The guard's rules are
  written on a laminated card they cannot be talked out of.
- **The escort** (`tools/loop.py`) walks Claude to the guard, counts how many
  times Claude may ask, watches the clock, and decides when the visit is over.

Claude is the visitor. A very capable, very fast-talking visitor who is
nevertheless never handed the keys.

## The responsibilities, side by side

| Claude decides | Application decides |
|---|---|
| *Whether* more evidence is needed | Whether the requested tool exists and is allowed |
| *Which* tool to ask for | Whether the input is valid (schema + business rules) |
| *What* arguments to propose | Whether this identity may call it (authorization) |
| How to interpret a result | Whether the result is well-formed and small enough |
| When it thinks it is done | When it is *actually* done (call / round / time limits) |
| — | Whether a destructive action is refused, no matter what |

Everything in the right-hand column is code that runs without consulting the
model. That asymmetry is the whole design.

## The wire protocol (what actually goes over HTTP)

One request/response round trip looks like this:

```
Application -> API :  system, messages, tools=[definitions], tool_choice
API -> Application :  content=[ ..., {type: tool_use, id, name, input} ], stop_reason=tool_use
Application        :  (guard) -> execute -> (guard) -> serialise
Application -> API :  messages + assistant turn + user turn [ {type: tool_result, tool_use_id, content, is_error} ]
API -> Application :  content=[text ...], stop_reason=end_turn      <- the loop ends
```

Three rules of the protocol that trip people up:

1. The assistant's `tool_use` turn must be appended to `messages` **before**
   the `tool_result` turn. Otherwise the API rejects the conversation.
2. Every `tool_use` **must** get a matching `tool_result` (same `tool_use_id`),
   even when the tool failed. A failure is a `tool_result` with `is_error: true`.
   Dropping it is a protocol error, not a security measure.
3. If Claude asked for several tools in one turn, all their results go back in
   **one** user message. Splitting them silently teaches the model to stop
   parallelising.

## Where this sits in Sentinel's request flow

Week 2's flow was a straight line: input → API → parse → schema → support.
Week 3 inserts a loop between "API" and "parse":

```
Incident text
    ↓ validate_input (Layer 0)
    ↓
┌───────────────────────── bounded loop (tools/loop.py) ─────────────────────┐
│  API call (tools + structured output)                                       │
│     ├─ stop_reason == tool_use ─► for each tool_use:                        │
│     │       pre hook → allow-list → schema → identity → limits              │
│     │       → bounded execute → output check → post hook (untrusted wrap)   │
│     │       → tool_result (is_error if any stage failed)                    │
│     │     append results; loop  (unless max_calls / max_rounds / clock)     │
│     └─ stop_reason == end_turn ─► exit loop with final text                 │
└─────────────────────────────────────────────────────────────────────────────┘
    ↓ parse (Layer 1) → schema (Layer 2) → support (Layer 3)     [unchanged]
Accepted analysis  OR  typed failure     +  a trace of every tool decision
```

Nothing from Week 2 was replaced. The output contract, the three validation
layers, the typed failures, the client and the config are all reused as-is.
Week 3 added one new failure category (`tool`) and one new package (`tools/`).

## What to take away

- The model's intelligence is spent on *choosing* evidence. The application's
  code is spent on *bounding* what that choice can cause.
- "Claude called a tool" is never a sentence that describes Sentinel. Claude
  requested; Sentinel decided; a mocked function ran.
