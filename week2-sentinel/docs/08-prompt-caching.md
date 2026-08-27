# Section 8 — Prompt caching

## The experiment

```
Request 1: stable contract (CACHING_SYSTEM_CONTRACT) + Incident A (inc-104)
Request 2: SAME stable contract              + Incident B (inc-205)
```
The contract carries `cache_control: {"type": "ephemeral"}`. If caching works,
request 1 writes the prefix to cache (`cache_creation_input_tokens > 0`) and
request 2 reads it back (`cache_read_input_tokens > 0`) — because only the
trailing incident changed, and caching matches on a stable PREFIX.

## Recorded result — a real limitation (not invented)

We ran it at three prefix sizes:

| stable contract size | cache_creation (req 1) | cache_read (req 2) |
|---|---|---|
| ~1132 tokens | 0 | 0 |
| ~1855 tokens | 0 | 0 |
| **~2489 tokens** (above Haiku's ~2048 minimum) | **0** | **0** |

Even above the minimum prefix length, request 1 wrote **zero** cache tokens — so
`cache_control` is not being honored at all on this path. 

**Conclusion:** prompt caching is **unavailable on the Claude subscription OAuth
token path** used here. It would require a real API key
(console.anthropic.com). Per the exercise instructions, we record this limitation
rather than fabricate cache numbers. The code (`prompt_cache.py`) is correct and
would show real cache hits with an API-key credential and a ≥2048-token prefix.

(Latency was similar across both requests, consistent with no cache acceleration.)

## Prompt caching vs KV cache vs conversation history vs application memory

These are constantly confused. They are four different things:

| Concept | Where it lives | Lifespan | What it does |
|---|---|---|---|
| **Prompt caching** | Anthropic servers, keyed by an exact token PREFIX | ~5 min (ephemeral) or 1h | Skips re-processing an unchanged prefix; you pay ~0.1x to read it instead of full input price. A cost/latency optimization. |
| **KV cache** | Inside the model, for ONE forward pass | The single request | The attention key/value tensors reused as the model generates each next token. An implementation detail of inference; you never control it directly. |
| **Conversation history** | Your request payload | However long you keep resending it | The `messages` array you send each turn. The API is stateless — "memory" of the chat is just you re-including prior turns. |
| **Application memory** | Your app's storage (DB, files, vector store) | As long as you persist it | State your application deliberately keeps across sessions/users — not part of the API at all. |

Key distinctions:
- Prompt caching is an **optimization** of sending the same prefix; it does not
  make the model "remember" anything. Its content is identical to what you sent.
- KV cache is **per-request** and internal; prompt caching is **cross-request**
  and server-managed.
- Conversation history is **you resending text**; it costs full input tokens
  every turn (unless a stable prefix of it is prompt-cached).
- Application memory is **your** responsibility; the model has no access to it
  unless you put it into the prompt.

A useful test: if deleting it changes *cost/latency* but not *the answer*, it's a
cache. If deleting it changes *what the model knows*, it's history or memory.

## Run it

```bash
uv run python -m sentinel.prompt_cache
```
