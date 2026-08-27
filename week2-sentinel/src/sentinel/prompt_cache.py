"""Section 8 — prompt caching experiment.

Run it:
    uv run python -m sentinel.prompt_cache

Setup the curriculum asks for:
    Request 1: stable system contract + Incident A (inc-104)
    Request 2: SAME system contract + Incident B (inc-205)

The stable contract is marked with cache_control. On request 1 the API writes it
to cache (cache_creation_input_tokens > 0). On request 2 the SAME prefix should
be read from cache (cache_read_input_tokens > 0) even though the incident differs
— because caching is a PREFIX match and only the trailing incident changed.

Caching has a minimum prefix length (~2048 tokens on Haiku), so we use the large
CACHING_SYSTEM_CONTRACT. If the prefix is still too short, or the account/model
doesn't cache, we RECORD THAT rather than invent a hit.
"""

from __future__ import annotations

from .client import build_client, map_api_exception
from .config import load_settings, read_incident
from .metrics import Timer, estimate_cost
from .prompts import CACHING_SYSTEM_CONTRACT, build_user_message


def _system_blocks():
    # A single system block, marked cacheable. Everything before the incident
    # (i.e. this whole block) becomes the cached prefix.
    return [{
        "type": "text",
        "text": CACHING_SYSTEM_CONTRACT,
        "cache_control": {"type": "ephemeral"},
    }]


def _run(client, model, max_tokens, incident_text, label):
    with Timer() as t:
        try:
            resp = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=_system_blocks(),
                messages=[{"role": "user", "content": build_user_message(incident_text)}],
            )
        except Exception as exc:
            raise map_api_exception(exc) from exc

    u = resp.usage
    cost = estimate_cost(model, u)
    print(f"\n[{label}]")
    print(f"  latency                     : {t.seconds:.1f}s")
    print(f"  uncached input tokens       : {u.input_tokens}")
    print(f"  cache_creation_input_tokens : {getattr(u, 'cache_creation_input_tokens', 0)}")
    print(f"  cache_read_input_tokens     : {getattr(u, 'cache_read_input_tokens', 0)}")
    print(f"  output tokens               : {u.output_tokens}")
    print(f"  estimated cost              : ${cost.total:.5f}")
    return u


def main() -> int:
    settings = load_settings()
    client = build_client(settings)
    model = settings.model

    # How big is the cacheable prefix? (min ~2048 tokens on Haiku)
    counted = client.messages.count_tokens(
        model=model,
        system=CACHING_SYSTEM_CONTRACT,
        messages=[{"role": "user", "content": "x"}],
    )
    print(f"→ model={model}")
    print(f"stable contract size ≈ {counted.input_tokens} tokens "
          f"(Haiku caching minimum is ~2048)")

    u1 = _run(client, model, settings.max_tokens, read_incident("inc-104"), "Request 1: contract + Incident A (inc-104)")
    u2 = _run(client, model, settings.max_tokens, read_incident("inc-205"), "Request 2: SAME contract + Incident B (inc-205)")

    created = getattr(u1, "cache_creation_input_tokens", 0) or 0
    read = getattr(u2, "cache_read_input_tokens", 0) or 0

    print("\n--- result ---")
    if created > 0 and read > 0:
        print(f"CACHE ENGAGED. Request 1 wrote {created} tokens; Request 2 read {read}"
              f" from cache.")
        print("The stable prefix was reused across two different incidents; only the")
        print("trailing incident text was billed as fresh input on request 2.")
    elif created > 0 and read == 0:
        print(f"Cache was WRITTEN ({created}) but not read on request 2 — the prefix")
        print("may have changed, expired, or fallen just under the minimum. Recorded as-is.")
    else:
        print("CACHE DID NOT ENGAGE (both cache_* counters are 0).")
        if counted.input_tokens < 2048:
            print(f"The prefix (~{counted.input_tokens} tokens) is below Haiku's ~2048 minimum,")
            print("so this is expected — enlarge the stable prefix to test caching.")
        else:
            print(f"The prefix (~{counted.input_tokens} tokens) is ABOVE the ~2048 minimum, yet")
            print("request 1 wrote 0 cache tokens — cache_control is not being honored on")
            print("this path. Conclusion: prompt caching is unavailable on the subscription")
            print("OAuth token path (it would require a real API key).")
        print("Per the exercise: recording the limitation rather than inventing a hit.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
