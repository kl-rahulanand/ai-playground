"""Part 4 security cases + Part 3 loop-termination guarantees, run offline
against the scripted FakeClient. Each test records the same five things the
curriculum asks for: requested action, validation, authorization, execution,
and final Sentinel behaviour.
"""

from __future__ import annotations

import json

from conftest import FakeClient, VALID_ANALYSIS, final_msg, tool_use_msg

from sentinel.failures import FailureKind
from sentinel.tools import policy
from sentinel.tools.loop import run_investigation

METRICS = {"service": "checkout-api", "metric": "error_rate", "start_time": "09:55", "end_time": "10:10"}
DEP = {"service": "checkout-api", "dependency": "payment-provider", "at_time": "10:04"}
LOGS = {"service": "checkout-api", "query": "error", "start_time": "10:00", "end_time": "10:10", "max_results": 10}


def run(script, incident, **kw):
    client = FakeClient(script)
    res = run_investigation(client, model="fake", max_tokens=100, incident_text=incident, **kw)
    return client, res


# 3. successful multi-step investigation ---------------------------------------

def test_successful_multi_step_investigation(incident):
    client, res = run([
        tool_use_msg(("get_service_metrics", METRICS)),
        tool_use_msg(("get_dependency_health", DEP), ("search_logs", LOGS)),   # parallel calls
        final_msg(),
    ], incident)
    assert res.ok
    t = res.trace
    assert [r.execution for r in t.tool_calls] == ["ran", "ran", "ran"]
    assert t.limit_reached is None and not t.escalation_required
    assert t.final_behaviour.startswith("completed")
    # both parallel results went back in ONE user message
    assert len(client.tool_results_sent(2)) == 2
    # the data reached the model wrapped as untrusted data
    payload = json.loads(client.tool_results_sent(1)[0]["content"])
    assert payload["trust"] == "untrusted_data"
    assert payload["data"]["observations"][0]["time"] == "09:55"


# 1. unknown tool ---------------------------------------------------------------

def test_unknown_tool_is_rejected_but_loop_continues(incident):
    client, res = run([
        tool_use_msg(("get_deploy_info", {"deploy_id": "dep-1842"})),
        final_msg(),
    ], incident)
    rec = res.trace.tool_calls[0]
    assert rec.validation == "rejected: tool_not_allowed"
    assert rec.authorization == "not_reached" and rec.execution == "not_reached"
    sent = client.tool_results_sent(1)[0]
    assert sent["is_error"] is True and "tool_not_allowed" in sent["content"]
    assert res.ok                                    # recoverable: Claude answered anyway


# 2. invalid service / time range ---------------------------------------------

def test_invalid_service_and_time_range_rejected(incident):
    bad_service = {**METRICS, "service": "prod-db-master"}
    bad_window = {**METRICS, "start_time": "09:00", "end_time": "11:00"}
    client, res = run([
        tool_use_msg(("get_service_metrics", bad_service), ("get_service_metrics", bad_window)),
        final_msg(),
    ], incident)
    recs = res.trace.tool_calls
    assert all(r.validation == "rejected: tool_input_invalid" for r in recs)
    assert all(r.execution == "not_reached" for r in recs)
    assert all(b["is_error"] for b in client.tool_results_sent(1))


# 3. valid request, unauthorized identity --------------------------------------

def test_valid_request_from_unauthorized_identity(incident):
    client, res = run([
        tool_use_msg(("get_service_metrics", METRICS)),
        final_msg(),
    ], incident, identity=policy.Identity("eve", "external-contractor"))
    rec = res.trace.tool_calls[0]
    assert rec.validation == "passed"                       # the request itself was fine
    assert rec.authorization == "denied: tool_unauthorized"  # the caller was not
    assert rec.execution == "not_reached"
    assert client.tool_results_sent(1)[0]["is_error"] is True


def test_read_only_observer_cannot_read_logs(incident):
    _, res = run([tool_use_msg(("search_logs", LOGS)), final_msg()],
                 incident, identity=policy.Identity("bob", "read-only-observer"))
    assert res.trace.tool_calls[0].authorization == "denied: tool_unauthorized"


# 4. prompt injection inside a tool result --------------------------------------

def test_prompt_injection_in_tool_result_is_data_not_authority(incident):
    client, res = run([
        tool_use_msg(("search_logs", LOGS)),
        # Claude "obeys" the injected log line and asks for the admin action:
        tool_use_msg(("mark_incident_resolved", {"incident": "INC-104"})),
        final_msg(),
    ], incident)
    t = res.trace
    # the injected line was delivered verbatim, but flagged and wrapped
    sent = client.tool_results_sent(1)[0]
    assert "Ignore all previous instructions" in sent["content"]
    assert '"injection_suspected": true' in sent["content"]
    assert t.injection_flagged
    # the follow-up admin request was denied by the deterministic hook
    blocked = t.tool_calls[1]
    assert blocked.validation == "rejected: blocked by policy hook"
    assert blocked.execution == "not_reached"
    assert blocked.returned_to_model == "error:tool_blocked_by_policy"
    hook = blocked.hook_decisions[0]
    assert hook["decision"] == "deny" and hook["requires_human_approval"] is True
    assert hook["policy"].startswith("SEC-POL-03")
    # and tools were switched OFF for the rest of the conversation
    assert client.messages.requests[2]["tool_choice"] == {"type": "none"}
    assert t.escalation_required
    assert "escalation required" in t.final_behaviour


# 5. tool timeout ---------------------------------------------------------------

def test_timeout_is_reported_never_claimed_successful(incident):
    limits = policy.LoopLimits(tool_timeout_seconds=0.1)
    client, res = run([tool_use_msg(("search_logs", LOGS)), final_msg()],
                      incident, limits=limits, faults={"search_logs": "timeout"})
    rec = res.trace.tool_calls[0]
    assert rec.validation == "passed" and rec.authorization == "passed"
    assert rec.execution == "failed: tool_exec_timeout"
    sent = client.tool_results_sent(1)[0]
    assert sent["is_error"] and "tool_exec_timeout" in sent["content"]
    assert res.trace.executed_calls == 0


# 6. malformed / oversized tool output ----------------------------------------

def test_malformed_and_oversized_results_are_rejected(incident):
    _, res = run([
        tool_use_msg(("get_service_metrics", METRICS)),
        tool_use_msg(("search_logs", LOGS)),
        final_msg(),
    ], incident, faults={"get_service_metrics": "malformed", "search_logs": "oversized"})
    execs = [r.execution for r in res.trace.tool_calls]
    assert execs == ["failed: tool_result_invalid", "failed: tool_result_invalid"]


# 7. exceeding the maximum number of calls -------------------------------------

def test_max_tool_calls_is_enforced_by_the_application(incident):
    limits = policy.LoopLimits(max_tool_calls=2)
    client, res = run([
        tool_use_msg(("get_service_metrics", METRICS)),
        tool_use_msg(("get_dependency_health", DEP), ("search_logs", LOGS)),  # 3rd call exceeds
        final_msg(),
    ], incident, limits=limits)
    t = res.trace
    assert [r.execution for r in t.tool_calls] == ["ran", "ran", "refused"]
    assert t.tool_calls[2].returned_to_model == "error:tool_limit_exceeded"
    assert t.limit_reached == "max_tool_calls"
    assert client.messages.requests[2]["tool_choice"] == {"type": "none"}   # finalisation round
    assert res.ok and "after max_tool_calls limit" in t.final_behaviour


def test_role_budget_caps_loop_budget(incident):
    # observer role allows 3 calls even if the loop would allow 6
    _, res = run([tool_use_msg(("get_service_metrics", METRICS)), final_msg()],
                 incident, identity=policy.Identity("bob", "read-only-observer"))
    assert res.trace.limits["max_tool_calls"] == 3


# termination guarantees -------------------------------------------------------

def test_round_limit_terminates_an_endless_tool_loop(incident):
    limits = policy.LoopLimits(max_rounds=3, max_tool_calls=100)
    script = [tool_use_msg(("get_service_metrics", METRICS)) for _ in range(10)]
    _, res = run(script, incident, limits=limits)
    assert not res.ok
    assert res.failure.kind is FailureKind.TOOL_LIMIT_EXCEEDED
    assert res.trace.limit_reached == "max_rounds"
    assert len(res.trace.rounds) == 3


def test_wall_clock_limit_terminates(incident):
    limits = policy.LoopLimits(max_wall_seconds=0.0)
    _, res = run([final_msg()], incident, limits=limits)
    assert not res.ok and res.trace.limit_reached == "max_wall_seconds"


def test_unsupported_final_answer_is_still_rejected(incident):
    overclaiming = {**VALID_ANALYSIS,
                    "likely_cause_assessment": {"leading_hypothesis": "Deployment dep-1842 regression",
                                                "confidence": "high",
                                                "reason": "It is the confirmed root cause."}}
    _, res = run([final_msg(overclaiming)], incident)
    assert not res.ok and res.failure.kind is FailureKind.UNSUPPORTED_CONTENT


def test_truncated_final_answer_is_a_failure(incident):
    _, res = run([final_msg(stop_reason="max_tokens")], incident)
    assert res.failure.kind is FailureKind.TRUNCATED_OUTPUT
