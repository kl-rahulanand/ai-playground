# Section 9 (cont.) — Tool-use lifecycle (preview)

This is a preview, not a full agent (that's Week 3). We inspect ONE tool exchange
to make the division of responsibility explicit.

## The lifecycle

```
Application sends a tool DEFINITION      (get_deploy_info, with a strict schema)
        ↓
Claude returns a tool_use REQUEST        (name + input + id) — it only ASKS
        ↓
Application VALIDATES and EXECUTES it     (our code checks the input and runs it)
        ↓
Application returns a tool_result         (referencing the tool_use id)
        ↓
Claude CONTINUES the response             (now with the result in hand)
```

## Who does what (the key point)

| Step | Who | What |
|---|---|---|
| Define tool | **Application** | Declares `get_deploy_info(deploy_id)` + JSON schema |
| Request tool | **Claude** | Emits a `tool_use` block; `stop_reason == "tool_use"`. Claude *cannot* run anything |
| Validate | **Application** | Checks `deploy_id` is a known string (rejects unknown/invalid) |
| Execute | **Application code** | Looks up the deploy record and returns data |
| Return result | **Application** | Sends a `tool_result` with the matching `tool_use_id` |
| Continue | **Claude** | Uses the result to refine its answer |

**Security takeaway:** Claude only *requests* a tool. Our application decides
whether the request is valid and what actually executes — Claude never touches our
systems directly. Authorization, sandboxing, and hooks (Week 3) live entirely on
the application side. This is the same boundary as the rest of Sentinel: the model
proposes, the application controls.

## What to notice in the run

- The `tool_use` block has a `name`, an `input` dict (parse it with `json.loads`
  patterns, never string-match), and an `id`.
- The `tool_result` MUST carry the same `tool_use_id`, and the assistant's
  tool_use turn must be appended to `messages` before the result.
- Our `_execute_get_deploy_info` validates the input first — an unknown
  `deploy_id` returns an error result, not a crash. That validation is the
  application's responsibility, not Claude's.

## Live run

(from `tool_preview.py` — captured output, trimmed)

```
STEP 1 — application sends the tool DEFINITION:
   tool: get_deploy_info(['deploy_id'])

STEP 2 — Claude responds. stop_reason=tool_use
   Claude says: I'll investigate the deployment first to understand what changed.
   Claude REQUESTS tool_use: name=get_deploy_info input={"deploy_id": "dep-1842"} id=toolu_01C4Rko2...

STEP 3 — application VALIDATES and EXECUTES (Claude cannot run code):
   executed get_deploy_info -> {"service":"checkout-api","changed":["Increased DB
   connection-pool acquisition timeout","Added a new synchronous call to the payments
   provider"],"migrations":"none","rollback_safe":true}

STEP 4 — application returns a tool_result referencing the tool_use id:
   tool_result for id=toolu_01C4Rko2...

STEP 5 — Claude CONTINUES with the tool result in hand:
   ...The new synchronous call to the payments provider is the likely culprit... when the
   provider errors, the synchronous call ties up checkout-api threads, exhausting the pool
   and raising DB latency... Recommendation: rollback (rollback_safe: true).
   stop_reason=end_turn
```

Notice the payoff: given **real evidence** (the deploy added a synchronous
provider call), Claude legitimately shifted from "no leading cause, low
confidence" to a specific hypothesis and a rollback recommendation. Contrast the
evidence-poor runs (Sections 3–6) where it correctly stayed cautious. Tools bring
in evidence that can properly change a conclusion — which is exactly why the
application, not the model, must control what those tools do.

## Run it

```bash
uv run python -m sentinel.tool_preview
```
