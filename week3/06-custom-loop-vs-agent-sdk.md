# Step 6 — Custom loop versus the Claude Agent SDK

## What was built

The same bounded investigation, twice:

| | Custom loop | Agent SDK |
|---|---|---|
| File | `tools/loop.py` + `investigate.py` | `agent_sdk_investigation.py` |
| Who runs the loop | Sentinel (`for round in range(max_rounds)`) | the SDK (`async for message in query(...)`) |
| How tools are exposed | `tools=[spec.definition ...]` on `messages.create` | in-process MCP server: `create_sdk_mcp_server(tools=[@tool ...])`; names become `mcp__sentinel__<tool>` |
| Where the guard runs | `ToolGate.handle()` inside the loop | **the same** `ToolGate.handle()` inside each `@tool` handler |
| Where the hook runs | stage 0 of the gate | **the same** `hooks.pre_tool_use`, registered as an SDK `PreToolUse` `HookMatcher` |
| Final answer | `output_config.format` on every request | `ClaudeAgentOptions(output_format=...)`; delivered via an internal `StructuredOutput` tool |
| Validation of the answer | `validate_response` (Layers 1-3) | **the same** `validate_response` |

One security implementation, two loops. That was the design goal: the SDK
should replace the escort, not the guard.

## Mental model: renting versus building the conveyor belt

The loop is a conveyor belt between the model and your tools. Building your own
means you see every item pass and can stop the belt anywhere. Renting the SDK's
belt gives you a good belt on day one, with hooks bolted on at fixed points,
but the belt's speed, its retries and what it tells you are its design, not
yours. The question is never "which belt is better"; it is "how much of the
belt do you need to see?"

## What the SDK did well

- **Less code.** No `stop_reason` handling, no message bookkeeping, no
  `tool_result` construction. The SDK module is about 40% shorter than
  `loop.py` + `investigate.py` for the same behaviour.
- **Hooks are first-class.** A `PreToolUse` callback that returns
  `permissionDecision: "deny"` really does stop the tool, and the SDK reports
  `permission_denials` on the result. Our policy function plugged in unchanged.
- **Built-in tools are opt-in.** `tools=[]` plus an explicit `allowed_tools`
  list meant the agent never had Bash, file or web access. That is the right
  default for Sentinel and it was one line.
- **It ran on the existing credentials.** The bundled CLI picked up the
  subscription token from `.env` (with a warning) and used `claude-haiku-4-5`.

## What the SDK made harder

- **No tool-call budget.** The SDK has `max_turns` but nothing like
  `max_tool_calls`. Sentinel's budget had to be re-implemented inside the hook.
- **Hidden internal tools.** With `output_format` set, the SDK delivers the
  final answer through a tool called `StructuredOutput`. The first version of
  the budget hook, written for "any tool", denied it three times and the agent
  could not finish. Fix: only `mcp__sentinel__*` names spend budget. You only
  learn this by reading a trace, not from the options object.
- **No `stop_reason`, no per-request timeout.** The wall clock had to be
  wrapped around the whole `query()` with `asyncio.timeout`; there is no
  "time remaining" to pass into each API call.
- **Cost is opaque until the end.** The SDK reports `total_cost_usd` on the
  result message; the custom loop sees `usage` after every round and could
  stop early on tokens if it wanted to.
- **The trace is thinner.** `tool_use_id` is not exposed to SDK tool
  handlers, so the trace numbers calls itself. Turn counts include internal
  turns (13 turns for 6 tool executions).

## Live results, same incident, same role, same model

| Run | Loop | Tool calls (attempted / executed) | Turns or rounds | Tokens or cost | Final |
|---|---|---|---|---|---|
| baseline | custom | 9 / 6 | 3 rounds | 16,886 in / 4,809 out (~$0.04) | validated analysis, low confidence, no leading cause |
| SDK run 1 (no `output_format`) | SDK | 9 / 6 | 10 turns | $0.045 reported | **rejected**: `malformed_response` (free-text JSON with a syntax error) |
| SDK run 2 (`output_format`, hook bug) | SDK | 11 / 6 | 13 turns | $0.156 reported | **rejected**: `unsupported_content` (Layer 3 R1: composite leading hypothesis not among candidates); budget hook had also denied `StructuredOutput` ×3 |
| SDK run 3 (`output_format`, hook fixed) | SDK | 7 / 6 | 11 turns | $0.114 reported, 207 s | **rejected**: `unsupported_content` (Layer 3 R1 again); budget correctly refused the 7th call; `StructuredOutput` allowed |

Three things the table shows:

1. **Structured output matters as much as in Week 2.** Without it, the SDK's
   final text was invalid JSON. With it, the shape was guaranteed. The
   application's own validators were still needed after that.
2. **Layer 3 does not care which loop produced the answer.** SDK run 2 was
   rejected for the same class of overclaiming Week 2 was built to catch. The
   security layer and the content layer are independent of the loop.
3. **The SDK costs more per investigation** here, mainly through extra
   turns and the larger default context the CLI harness carries.

A fourth, uncomfortable one: **none of the three SDK runs passed Layer 3**,
while the custom loop passed in five of seven live runs. The rejections were
all the same rule (R1: the leading hypothesis must be one of the candidate
hypotheses; the model wrote a long composite sentence instead). The custom
loop hit the same rule twice (timeout and oversized reruns). This is a Week 2
heuristic interacting with Haiku's phrasing, not a tool-layer difference, and
the project rule is not to weaken Layer 3 to make a response pass. It is
recorded here because it is what happened, and because it shows the content
validator is loop-agnostic: it rejected both loops' answers for the same
reason. A follow-up is noted at the end of the reflection.

## The eight-row comparison

| Area | Custom loop | Agent SDK |
|---|---|---|
| **Control** | Total. Every request, `tool_choice`, timeout, message and limit is Sentinel's code. `tool_choice: none` after a terminal failure is one line. | Partial. Hooks, `allowed_tools`, `max_turns`, `output_format`. Internal tools and turn structure are the SDK's. |
| **Code required** | ~330 lines (`loop.py` + `investigate.py`) including trace records. | ~200 lines, of which ~60 re-implement the budget and trace the SDK lacks. |
| **Tool handling** | Explicit `tool_use` → gate → `tool_result` with `is_error`. Parallel calls batched by us. | `@tool` handlers on an in-process MCP server; the SDK batches and returns results. Same gate inside. |
| **Safety enforcement** | Gate + hooks in-process; limits invisible to the model; API-level `tool_choice` as a second lock. | `PreToolUse` deny works and is audited by the SDK. No native call budget; internal tools must be exempted carefully. |
| **Traceability** | Full: per-round `stop_reason`, per-call stage results, tokens per round, `tool_use_id`s. | Partial: `ResultMessage` totals, `permission_denials`, our own records from inside handlers. No `tool_use_id` in handlers. |
| **Failure handling** | Typed `SentinelFailure` for every path: API error, truncation, limits, validation. | `is_error` + `subtype` on the result; API errors surface as `api_error_status`. Our validators still run after. |
| **Latency and cost** | 3 rounds, ~105 s, ~$0.04 for the baseline. | 10-13 turns, 60-200 s, $0.045-0.16 reported. Slower and 1-4× the cost in these runs. |
| **Deployment complexity** | One Python process, one HTTP client, no subprocess. | Spawns the bundled Claude Code CLI as a subprocess; needs its runtime, credentials resolution and version alignment. |

## Decision

**Sentinel should use the custom loop at its current stage.**

Reasons, in order of weight:

1. **The thing Week 3 is about is control.** Sentinel's value is that limits,
   permissions and termination are provably the application's. The custom loop
   makes every one of those a visible line of code and a testable branch
   (39 offline tests). The SDK can be made to enforce the same rules, but
   through indirection that already bit once (`StructuredOutput`).
2. **Sentinel needs three tools, not thirty.** The SDK's strengths, built-in
   file/shell tools, sessions, subagents, MCP plumbing, are for coding-style
   agents with a large tool surface. Sentinel has a fixed, tiny, read-only
   surface and no need for a filesystem.
3. **Cost and latency favour the loop** for the same outcome.
4. **The trace is the product.** An incident tool that cannot show a reviewer
   exactly which request was refused at which stage, with which policy, is
   not finished. The custom loop's trace is richer with less effort.

When to revisit: if Sentinel grows real tool breadth (many services, MCP
servers, file evidence), needs multi-turn sessions with a human in the loop, or
needs subagents (Step 7), the SDK's harness starts paying for its opacity. The
`ToolGate` and hooks were written so that switch would not require rewriting
the security layer, and Step 6 proves that: the SDK version reuses them as-is.
