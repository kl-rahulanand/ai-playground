"""Shared test scaffolding: a scripted fake Anthropic client.

The loop only ever calls `client.with_options(...).messages.create(...)`, so a
fake that returns pre-built `anthropic.types.Message` objects in order lets us
drive every branch of the loop deterministically and offline. The fake also
records each request it receives so tests can assert what the APPLICATION
sent back to the model (is_error flags, tool_choice, envelope contents).
"""

from __future__ import annotations

import copy
import json

import pytest
from anthropic.types import Message, TextBlock, ToolUseBlock, Usage

# A cautious, well-supported analysis that passes all three validation layers.
VALID_ANALYSIS = {
    "known_facts": [
        {"fact": "Checkout error rate rose from 0.4% to 9% at 10:04 UTC",
         "source_text": "failures increased from 0.4% to 9%"},
        {"fact": "get_service_metrics: error_rate was 0.5 at 10:02 and 9.0 at 10:04",
         "source_text": "tool result get_service_metrics"},
    ],
    "assumptions": [{"assumption": "Times in the brief are UTC", "reason": "stated as UTC"}],
    "missing_information": [
        {"information": "Error rate split by application version",
         "why_needed": "Discriminates deployment regression from a shared dependency"}
    ],
    "candidate_hypotheses": [
        {"hypothesis": "Deployment dep-1842 regression",
         "supporting_evidence": ["Deploy completed at 10:01, errors rose at 10:04"],
         "contradicting_or_limiting_evidence": ["Payment provider also reported errors"],
         "evidence_needed": ["Per-version error rates"]},
        {"hypothesis": "Downstream payment-provider outage",
         "supporting_evidence": ["Provider reported intermittent errors"],
         "contradicting_or_limiting_evidence": ["Explains only part of the errors"],
         "evidence_needed": ["Share of failed requests carrying provider errors"]},
    ],
    "likely_cause_assessment": {
        "leading_hypothesis": None, "confidence": "low",
        "reason": "The evidence does not yet discriminate between the hypotheses.",
    },
    "reversible_next_actions": [
        {"action": "Compare error rate by version", "expected_observation": "New version fails more if regression",
         "risk_or_precondition": "none"}
    ],
    "rollback_recommendation": {
        "decision": "insufficient_evidence",
        "reason": "No hypothesis is supported strongly enough to justify a rollback.",
        "preconditions": ["Per-version comparison completed"],
    },
    "uncertainty_statement": "It is unresolved whether the deployment, the provider, or the database drove the failures.",
}


def _msg(content, stop_reason):
    return Message(id="msg_test", type="message", role="assistant", model="fake",
                   content=content, stop_reason=stop_reason, stop_sequence=None,
                   usage=Usage(input_tokens=10, output_tokens=5))


def tool_use_msg(*calls: tuple[str, dict], ids: list[str] | None = None) -> Message:
    """A response in which Claude requests one or more tools."""
    blocks = []
    for i, (name, args) in enumerate(calls):
        tid = (ids or [])[i] if ids and i < len(ids) else f"toolu_{i}"
        blocks.append(ToolUseBlock(type="tool_use", id=tid, name=name, input=args))
    return _msg(blocks, "tool_use")


def final_msg(analysis: dict | None = None, stop_reason: str = "end_turn") -> Message:
    text = json.dumps(analysis if analysis is not None else VALID_ANALYSIS)
    return _msg([TextBlock(type="text", text=text)], stop_reason)


class FakeMessages:
    def __init__(self, script: list[Message]):
        self.script = list(script)
        self.requests: list[dict] = []

    def create(self, **kwargs) -> Message:
        # The loop mutates one `messages` list in place; snapshot it so each
        # recorded request reflects what was sent AT THAT MOMENT.
        self.requests.append({**kwargs, "messages": copy.deepcopy(kwargs["messages"])})
        if not self.script:
            raise AssertionError("fake client ran out of scripted responses")
        return self.script.pop(0)


class FakeClient:
    def __init__(self, script: list[Message]):
        self.messages = FakeMessages(script)

    def with_options(self, **_):
        return self

    # helpers for assertions -------------------------------------------------
    def tool_results_sent(self, request_index: int) -> list[dict]:
        """The tool_result blocks in the user turn of the Nth request."""
        msgs = self.messages.requests[request_index]["messages"]
        last_user = msgs[-1]
        assert last_user["role"] == "user"
        return [b for b in last_user["content"] if isinstance(b, dict) and b.get("type") == "tool_result"]


@pytest.fixture
def incident() -> str:
    return ("INC-104 — Checkout failures after a deployment. At 10:04 UTC the "
            "checkout error-rate alert fired after failures increased from 0.4% to 9%.")
