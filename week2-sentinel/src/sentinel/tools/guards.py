"""Pure guard functions layered in front of the registry.

Each guard takes a request and either returns normally or raises a ToolError.
None of them call the model, none of them have side effects, and together they
implement Part 3 of the milestone:

    verify the tool is allow-listed      -> check_allowlisted
    validate its input schema            -> validate_input
    check identity and permissions       -> authorize
    enforce time-range and size limits   -> enforce_value_limits
    execute the mocked tool (bounded)    -> execute_bounded
    validate and limit the result        -> validate_output

They are ordered from cheapest/most-general to most-specific, so a bad request
is rejected as early as possible and never reaches the data source.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass

from pydantic import ValidationError

from ..failures import FailureKind, ToolError
from . import policy
from .registry import TOOL_SPECS, ToolSpec


# ---------------------------------------------------------------------------
# A tool request as the loop sees it. `identity` comes from the application.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ToolRequest:
    tool_use_id: str
    name: str
    raw_input: dict
    identity: policy.Identity


# ---------------------------------------------------------------------------
# 1. Allow-list
# ---------------------------------------------------------------------------

def check_allowlisted(req: ToolRequest) -> ToolSpec:
    """The name must be on the application allow-list AND exist in the registry."""
    if req.name not in policy.ALLOWED_TOOLS:
        raise ToolError(
            FailureKind.TOOL_NOT_ALLOWED,
            f"Tool {req.name!r} is not on the allow-list.",
            detail=f"allowed: {sorted(policy.ALLOWED_TOOLS)}",
        )
    spec = TOOL_SPECS.get(req.name)
    if spec is None:  # allow-listed but not implemented: a config bug, still refuse
        raise ToolError(
            FailureKind.TOOL_NOT_ALLOWED,
            f"Tool {req.name!r} is allow-listed but has no implementation.",
        )
    return spec


# ---------------------------------------------------------------------------
# 2. Input schema (the SAME Pydantic model that produced the schema Claude saw)
# ---------------------------------------------------------------------------

def validate_input(spec: ToolSpec, raw_input: object) -> dict:
    """Returns the validated, normalised argument dict (defaults filled in)."""
    if not isinstance(raw_input, dict):
        raise ToolError(
            FailureKind.TOOL_INPUT_INVALID,
            "Tool input must be a JSON object.",
            detail=f"got {type(raw_input).__name__}",
        )
    try:
        model = spec.input_model.model_validate(raw_input)
    except ValidationError as exc:
        errs = exc.errors()[:4]
        summary = "; ".join(
            f"{'.'.join(str(p) for p in e['loc']) or '<root>'}: {e['msg']}" for e in errs
        )
        raise ToolError(
            FailureKind.TOOL_INPUT_INVALID,
            f"Input for {spec.name!r} failed schema validation.",
            detail=summary,
        ) from exc
    return model.model_dump()


# ---------------------------------------------------------------------------
# 3. Identity and permissions (least privilege)
# ---------------------------------------------------------------------------

def authorize(req: ToolRequest, args: dict) -> policy.RolePermissions:
    """Is THIS identity allowed to call THIS tool on THIS service?"""
    perms = policy.permissions_for(req.identity)
    if perms is None:
        raise ToolError(
            FailureKind.TOOL_UNAUTHORIZED,
            f"Identity {req.identity.name!r} has unknown role {req.identity.role!r}.",
        )
    if req.name not in perms.tools:
        raise ToolError(
            FailureKind.TOOL_UNAUTHORIZED,
            f"Role {req.identity.role!r} may not call {req.name!r}.",
            detail=f"role may call: {sorted(perms.tools) or 'nothing'}",
        )
    service = args.get("service")
    if service is not None and service not in perms.services:
        raise ToolError(
            FailureKind.TOOL_UNAUTHORIZED,
            f"Role {req.identity.role!r} may not access service {service!r}.",
            detail=f"role may access: {sorted(perms.services) or 'nothing'}",
        )
    return perms


# ---------------------------------------------------------------------------
# 4. Value limits: services, dependencies, time windows, sizes
# ---------------------------------------------------------------------------

def _minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def _check_time(label: str, t: str) -> None:
    if not (policy.EARLIEST_TIME <= t <= policy.LATEST_TIME):
        raise ToolError(
            FailureKind.TOOL_INPUT_INVALID,
            f"{label} {t!r} is outside the permitted range "
            f"{policy.EARLIEST_TIME}-{policy.LATEST_TIME}.",
        )


def enforce_value_limits(spec: ToolSpec, args: dict) -> None:
    """Application-level rules the JSON schema cannot express."""
    service = args.get("service")
    if service is not None and service not in policy.ALLOWED_SERVICES:
        raise ToolError(
            FailureKind.TOOL_INPUT_INVALID,
            f"Service {service!r} is not an approved service.",
            detail=f"approved: {sorted(policy.ALLOWED_SERVICES)}",
        )

    dependency = args.get("dependency")
    if dependency is not None:
        allowed = policy.ALLOWED_DEPENDENCIES.get(service, frozenset())
        if dependency not in allowed:
            raise ToolError(
                FailureKind.TOOL_INPUT_INVALID,
                f"Dependency {dependency!r} is not approved for {service!r}.",
                detail=f"approved: {sorted(allowed)}",
            )

    if "at_time" in args:
        _check_time("at_time", args["at_time"])

    if "start_time" in args and "end_time" in args:
        start, end = args["start_time"], args["end_time"]
        _check_time("start_time", start)
        _check_time("end_time", end)
        if _minutes(end) < _minutes(start):
            raise ToolError(
                FailureKind.TOOL_INPUT_INVALID,
                f"end_time {end!r} is before start_time {start!r}.",
            )
        span = _minutes(end) - _minutes(start)
        if span > policy.MAX_WINDOW_MINUTES:
            raise ToolError(
                FailureKind.TOOL_INPUT_INVALID,
                f"Time window of {span} minutes exceeds the {policy.MAX_WINDOW_MINUTES}-minute limit.",
            )

    if "max_results" in args and args["max_results"] > policy.MAX_LOG_LINES:
        raise ToolError(
            FailureKind.TOOL_INPUT_INVALID,
            f"max_results {args['max_results']} exceeds the limit of {policy.MAX_LOG_LINES}.",
        )


# ---------------------------------------------------------------------------
# 5. Bounded execution
# ---------------------------------------------------------------------------

def execute_bounded(spec: ToolSpec, args: dict, *, timeout_seconds: float) -> dict:
    """Run the tool with a hard deadline.

    If the deadline passes we raise TOOL_EXEC_TIMEOUT. Crucially we do NOT
    return partial data and we do NOT claim success: a timeout is an explicit
    failure state the model has to reason about.
    """
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(spec.execute, args)
        try:
            return future.result(timeout=timeout_seconds)
        except FutureTimeout as exc:
            future.cancel()
            raise ToolError(
                FailureKind.TOOL_EXEC_TIMEOUT,
                f"Tool {spec.name!r} did not finish within {timeout_seconds:.1f}s.",
            ) from exc
        except ToolError:
            raise
        except Exception as exc:  # a bug inside the tool must not crash the loop
            raise ToolError(
                FailureKind.TOOL_RESULT_INVALID,
                f"Tool {spec.name!r} raised {type(exc).__name__}.",
                detail=str(exc)[:200],
            ) from exc


# ---------------------------------------------------------------------------
# 6. Output validation and result-size limits
# ---------------------------------------------------------------------------

_REQUIRED_KEYS: dict[str, tuple[str, ...]] = {
    "get_service_metrics": ("service", "metric", "observations"),
    "get_dependency_health": ("service", "dependency", "at_time", "status"),
    "search_logs": ("service", "query", "returned", "lines"),
}


def validate_output(spec: ToolSpec, result: object, *, max_bytes: int) -> str:
    """Check the tool returned the predictable structure we promised, within
    size limits. Returns the JSON string that will go into the tool_result."""
    if not isinstance(result, dict):
        raise ToolError(
            FailureKind.TOOL_RESULT_INVALID,
            f"Tool {spec.name!r} returned {type(result).__name__}, expected object.",
        )
    missing = [k for k in _REQUIRED_KEYS.get(spec.name, ()) if k not in result]
    if missing:
        raise ToolError(
            FailureKind.TOOL_RESULT_INVALID,
            f"Tool {spec.name!r} result is missing required keys.",
            detail=f"missing: {missing}",
        )
    obs = result.get("observations")
    if isinstance(obs, list) and len(obs) > policy.MAX_OBSERVATIONS:
        raise ToolError(
            FailureKind.TOOL_RESULT_INVALID,
            f"Tool {spec.name!r} returned {len(obs)} observations (limit {policy.MAX_OBSERVATIONS}).",
        )
    lines = result.get("lines")
    if isinstance(lines, list) and len(lines) > policy.MAX_LOG_LINES:
        raise ToolError(
            FailureKind.TOOL_RESULT_INVALID,
            f"Tool {spec.name!r} returned {len(lines)} lines (limit {policy.MAX_LOG_LINES}).",
        )
    try:
        text = json.dumps(result, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise ToolError(
            FailureKind.TOOL_RESULT_INVALID,
            f"Tool {spec.name!r} result is not JSON-serialisable.",
            detail=str(exc)[:200],
        ) from exc
    size = len(text.encode("utf-8"))
    if size > max_bytes:
        raise ToolError(
            FailureKind.TOOL_RESULT_INVALID,
            f"Tool {spec.name!r} result is {size} bytes (limit {max_bytes}).",
        )
    return text
