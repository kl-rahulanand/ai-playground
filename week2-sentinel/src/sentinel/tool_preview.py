"""Section 9 — tool-use lifecycle preview.

Run it:
    uv run python -m sentinel.tool_preview

We do NOT build a full agent here (that's Week 3). We inspect ONE tool exchange
and annotate each step, to make the division of responsibility explicit:

    Application sends a tool DEFINITION
            ↓
    Claude returns a tool_use REQUEST        <- Claude requests; it cannot run code
            ↓
    Application VALIDATES and EXECUTES it     <- the APPLICATION controls execution
            ↓
    Application returns a tool_result
            ↓
    Claude CONTINUES the response

The security point: Claude only *asks* to use a tool. Our code decides whether
the request is valid and what actually runs. Claude never touches our systems.
"""

from __future__ import annotations

import json

from .client import build_client, map_api_exception
from .config import load_settings, read_incident

# --- What the APPLICATION exposes: a tool definition (strict schema) ---
TOOL = {
    "name": "get_deploy_info",
    "description": "Look up what a deployment changed, by deployment id.",
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "deploy_id": {"type": "string", "description": "e.g. dep-1842"},
        },
        "required": ["deploy_id"],
        "additionalProperties": False,
    },
}

# --- Fictional deployment records the application can serve ---
_DEPLOY_DB = {
    "dep-1842": {
        "service": "checkout-api",
        "changed": ["Increased DB connection-pool acquisition timeout",
                    "Added a new synchronous call to the payments provider"],
        "migrations": "none",
        "rollback_safe": True,
    }
}


def _execute_get_deploy_info(args: dict) -> dict:
    """The APPLICATION validates and executes the requested tool call.

    Validation the application (not Claude) performs:
      * the requested tool input matches our schema (deploy_id is a string), and
      * the deploy_id is one we actually know about.
    """
    deploy_id = args.get("deploy_id", "")
    if not isinstance(deploy_id, str) or not deploy_id:
        return {"error": "invalid deploy_id"}
    record = _DEPLOY_DB.get(deploy_id)
    if record is None:
        return {"error": f"unknown deploy_id {deploy_id!r}"}
    return record


def main() -> int:
    settings = load_settings()
    client = build_client(settings)
    incident = read_incident("inc-104")

    system = (
        "You are investigating an incident. Before drawing conclusions, if a "
        "deployment is mentioned, use the get_deploy_info tool to check what it "
        "changed. Then state briefly whether that changes your leading hypothesis."
    )
    messages = [{"role": "user", "content":
                 f"Here is the incident. Investigate the deployment first.\n\n{incident}"}]

    print(f"→ model={settings.model}\n")
    print("STEP 1 — application sends the tool DEFINITION:")
    print(f"   tool: {TOOL['name']}({list(TOOL['input_schema']['properties'])})\n")

    try:
        resp = client.messages.create(
            model=settings.model, max_tokens=1024,
            system=system, tools=[TOOL], messages=messages,
        )
    except Exception as exc:
        raise map_api_exception(exc) from exc

    print(f"STEP 2 — Claude responds. stop_reason={resp.stop_reason}")
    tool_use = next((b for b in resp.content if b.type == "tool_use"), None)
    for b in resp.content:
        if b.type == "text" and b.text.strip():
            print(f"   Claude says: {b.text.strip()[:160]}")
    if tool_use is None:
        print("   (Claude did not request the tool this run — rerun to see it.)")
        return 0
    print(f"   Claude REQUESTS tool_use: name={tool_use.name} "
          f"input={json.dumps(tool_use.input)} id={tool_use.id}")

    print("\nSTEP 3 — application VALIDATES and EXECUTES (Claude cannot run code):")
    result = _execute_get_deploy_info(tool_use.input)
    print(f"   validated input, executed get_deploy_info -> {json.dumps(result)}")

    print("\nSTEP 4 — application returns a tool_result referencing the tool_use id:")
    messages.append({"role": "assistant", "content": resp.content})
    messages.append({"role": "user", "content": [{
        "type": "tool_result",
        "tool_use_id": tool_use.id,
        "content": json.dumps(result),
    }]})
    print(f"   tool_result for id={tool_use.id}")

    print("\nSTEP 5 — Claude CONTINUES with the tool result in hand:")
    try:
        cont = client.messages.create(
            model=settings.model, max_tokens=1024,
            system=system, tools=[TOOL], messages=messages,
        )
    except Exception as exc:
        raise map_api_exception(exc) from exc
    for b in cont.content:
        if b.type == "text":
            print(f"   {b.text.strip()}")
    print(f"\n   stop_reason={cont.stop_reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
