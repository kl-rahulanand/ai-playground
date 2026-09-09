"""The application's AUTHORITY over tools. Nothing in this file is negotiable by
the model: it cannot read it, argue with it, or change it at runtime.

Four kinds of decision live here:

  1. Allow-list        -> which tool NAMES may ever be requested.
  2. Value limits      -> which services / dependencies / windows / sizes are OK.
  3. Identity + roles  -> WHO may call WHICH tool on WHICH service (least privilege).
  4. Blocked actions   -> destructive verbs that are refused no matter who asks.
  + Limits             -> max tool calls, max wall-clock time, per-tool timeout,
                          max result size. The loop enforces these; the model
                          never sees or controls them.

Everything is a frozen constant or a frozen dataclass. If you want to change
what Sentinel is allowed to do, you change THIS FILE and redeploy — that is the
whole point of an external authorization policy.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# 1. Allow-list of tool names. A name not in this set is rejected before any
#    schema validation — we do not even look at its input.
# ---------------------------------------------------------------------------
ALLOWED_TOOLS: frozenset[str] = frozenset({
    "get_service_metrics",
    "get_dependency_health",
    "search_logs",
})

# ---------------------------------------------------------------------------
# 2. Value limits.
# ---------------------------------------------------------------------------
# Services Sentinel is allowed to look at AT ALL (any identity).
ALLOWED_SERVICES: frozenset[str] = frozenset({"checkout-api", "payments-gateway"})

# Dependencies that may be queried, per service.
ALLOWED_DEPENDENCIES: dict[str, frozenset[str]] = {
    "checkout-api": frozenset({"database", "payment-provider", "session-cache"}),
    "payments-gateway": frozenset({"database", "payment-provider"}),
}

# Only this fictional incident day exists in the mock data. Windows must fall
# inside these bounds and be no longer than MAX_WINDOW_MINUTES.
EARLIEST_TIME = "09:00"
LATEST_TIME = "12:00"
MAX_WINDOW_MINUTES = 60

# Result-size ceilings (enforced on OUTPUT, not just input). A tool that returns
# more than this is treated as misbehaving, even if the request was fine.
MAX_RESULT_BYTES = 4_000
MAX_OBSERVATIONS = 50
MAX_LOG_LINES = 20

# ---------------------------------------------------------------------------
# 3. Identities and roles — least privilege.
#
# The identity is supplied by the APPLICATION (config / CLI flag / caller of
# run_investigation). It never comes from the model or from a tool result.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Identity:
    """Who is asking Sentinel to investigate. Carried through every tool call."""
    name: str
    role: str


@dataclass(frozen=True)
class RolePermissions:
    tools: frozenset[str]             # tool names this role may call
    services: frozenset[str]          # services this role may look at
    max_tool_calls: int               # per-investigation budget for this role


ROLE_PERMISSIONS: dict[str, RolePermissions] = {
    # Full read-only investigation rights on the incident's services.
    "on-call-engineer": RolePermissions(
        tools=ALLOWED_TOOLS,
        services=ALLOWED_SERVICES,
        max_tool_calls=6,
    ),
    # May look at metrics only — no dependency health, no raw logs.
    "read-only-observer": RolePermissions(
        tools=frozenset({"get_service_metrics"}),
        services=frozenset({"checkout-api"}),
        max_tool_calls=3,
    ),
    # Exists to prove a VALID request from the wrong identity is refused.
    "external-contractor": RolePermissions(
        tools=frozenset(),
        services=frozenset(),
        max_tool_calls=2,   # has a budget, has NO permissions -> authorization denies
    ),
}

DEFAULT_IDENTITY = Identity(name="sentinel-demo-user", role="on-call-engineer")


def permissions_for(identity: Identity) -> RolePermissions | None:
    """Look up a role's permissions. Unknown role -> None (deny everything)."""
    return ROLE_PERMISSIONS.get(identity.role)


# ---------------------------------------------------------------------------
# 4. Blocked (destructive / write) actions.
#
# None of these exist as tools in the registry, so they can never execute. The
# hook still checks for them explicitly so that IF one were ever advertised by
# mistake, or IF the model invents the name after reading an injected log line,
# it is refused with an audit record — not merely "unknown tool".
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class BlockedAction:
    reason: str
    policy: str
    requires_human_approval: bool


BLOCKED_ACTIONS: dict[str, BlockedAction] = {
    "delete_deployment": BlockedAction(
        reason="Deleting a deployment is destructive and irreversible.",
        policy="SEC-POL-01: Sentinel is read-only; no production writes.",
        requires_human_approval=True,
    ),
    "restart_production_service": BlockedAction(
        reason="Restarting production changes live state and hides evidence.",
        policy="SEC-POL-01: Sentinel is read-only; no production writes.",
        requires_human_approval=True,
    ),
    "rotate_production_credentials": BlockedAction(
        reason="Credential rotation is a security operation, not an analysis step.",
        policy="SEC-POL-02: credential changes require the security on-call.",
        requires_human_approval=True,
    ),
    "mark_incident_resolved": BlockedAction(
        reason="Only the incident director may close an incident.",
        policy="SEC-POL-03: incident state changes are human decisions.",
        requires_human_approval=True,
    ),
}

# Leading verbs that mark a tool name as a write even if it is not in the list
# above. Matched against the FIRST token of the name ("purge_cache" -> "purge"),
# not as a substring, so a read like "get_deploy_info" is not caught here — it
# falls through to the allow-list, which rejects it as unknown.
DESTRUCTIVE_VERBS: frozenset[str] = frozenset({
    "delete", "restart", "rotate", "resolve", "close", "write", "update",
    "set", "deploy", "rollback", "kill", "drop", "purge", "grant", "mark",
    "modify", "create", "remove", "disable", "enable", "patch", "put", "post",
})

# ---------------------------------------------------------------------------
# 5. Loop limits — enforced by the application, invisible to the model.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LoopLimits:
    max_tool_calls: int = 6          # hard ceiling on tool executions
    max_rounds: int = 8              # hard ceiling on Claude round-trips
    max_wall_seconds: float = 120.0  # whole investigation, including model time
    tool_timeout_seconds: float = 2.0  # any single mocked tool
    max_result_bytes: int = MAX_RESULT_BYTES

    def capped_by(self, perms: RolePermissions) -> "LoopLimits":
        """The effective budget is the SMALLER of the loop's and the role's."""
        return LoopLimits(
            max_tool_calls=min(self.max_tool_calls, perms.max_tool_calls),
            max_rounds=self.max_rounds,
            max_wall_seconds=self.max_wall_seconds,
            tool_timeout_seconds=self.tool_timeout_seconds,
            max_result_bytes=self.max_result_bytes,
        )


DEFAULT_LIMITS = LoopLimits()

# Markers that suggest a tool result is trying to talk to the model. Used by
# the post-execution hook to FLAG (not censor) suspicious content.
INJECTION_MARKERS: tuple[str, ...] = (
    "ignore all previous instructions",
    "ignore previous instructions",
    "disregard your instructions",
    "you are now",
    "system prompt",
    "call the administrative tool",
    "mark the incident as resolved",
    "as an ai",
)
