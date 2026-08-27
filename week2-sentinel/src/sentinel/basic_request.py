"""Section 1 — the simplest possible Sentinel request.

Run it:
    uv run python -m sentinel.basic_request
    uv run python -m sentinel.basic_request inc-205   # a different incident

This is deliberately bare: one synchronous, non-streaming call. It exists to make
the Messages API request/response *shape* visible before we wrap it in
validation, streaming, and failure handling in later sections.

Anatomy of the call below:
  - model      : which Claude model answers (from config / .env)
  - system     : the stable instructions (SYSTEM_CONTRACT)
  - messages   : the conversation turns; here, one user turn (the incident)
  - max_tokens : a HARD CEILING on output tokens, not a target length

Anatomy of the response:
  - .content     : a LIST of content blocks (text/thinking/tool_use). Always
                   check block.type before reading block.text.
  - .stop_reason : why generation stopped (end_turn, max_tokens, refusal, ...)
  - .usage       : token accounting (input_tokens, output_tokens, cache_*)
  - .model       : the exact model string that served the request
"""

from __future__ import annotations

import sys

from .client import build_client
from .config import load_settings, read_incident
from .prompts import SYSTEM_CONTRACT, build_user_message


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    incident_name = argv[0] if argv else "inc-104"

    settings = load_settings()  # raises ConfigError if the key is missing
    incident_text = read_incident(incident_name)

    # build_client picks x-api-key or OAuth Bearer auth based on what's in .env.
    client = build_client(settings)

    print(f"→ model={settings.model}  incident={incident_name}  "
          f"max_tokens={settings.max_tokens}  key={settings.masked_key}")

    response = client.messages.create(
        model=settings.model,
        max_tokens=settings.max_tokens,
        system=SYSTEM_CONTRACT,
        messages=[
            {"role": "user", "content": build_user_message(incident_text)},
        ],
    )

    # --- Inspect the response structure ---
    print("\n=== response metadata ===")
    print(f"served-by model : {response.model}")
    print(f"stop_reason     : {response.stop_reason}")
    print(f"request id      : {response._request_id}")
    print(f"input tokens    : {response.usage.input_tokens}")
    print(f"output tokens   : {response.usage.output_tokens}")

    # stop_reason == 'max_tokens' means the output was truncated — a partial
    # answer we must not trust. We surface it loudly here; Section 2 rejects it.
    if response.stop_reason == "max_tokens":
        print("\n!! WARNING: output was truncated (hit max_tokens). "
              "This response is incomplete and must not be accepted as-is.")

    print("\n=== content blocks ===")
    for i, block in enumerate(response.content):
        print(f"[block {i}] type={block.type}")
        if block.type == "text":
            print(block.text)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
