"""Sentinel's structured-output contract.

Week 1 described this shape in prose inside the prompt. Week 2 makes it CODE:
these Pydantic models are the single source of truth for

  1. the JSON Schema we send to the API (structured output), and
  2. the validated Python object we accept internally.

Because it's one definition, the schema the model must satisfy and the type the
application relies on can never drift apart.

Field names carry Week 1's discipline forward: every hypothesis must state both
its supporting AND its contradicting/limiting evidence, plus what evidence is
still needed. The confidence and rollback decision are constrained enums.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Confidence = Literal["low", "medium", "high"]
RollbackDecision = Literal[
    "rollback", "do_not_rollback", "conditional", "insufficient_evidence"
]


class Fact(BaseModel):
    fact: str = Field(description="An observation stated directly by the incident brief.")
    source_text: str = Field(description="The phrase in the brief this fact comes from.")


class Assumption(BaseModel):
    assumption: str = Field(description="Something taken as given but not proven.")
    reason: str = Field(description="Why this assumption is being made.")


class MissingInfo(BaseModel):
    information: str = Field(description="A specific piece of information not in the brief.")
    why_needed: str = Field(description="What decision this information would inform.")


class Hypothesis(BaseModel):
    hypothesis: str = Field(description="A candidate explanation for the incident.")
    supporting_evidence: list[str] = Field(
        description="Evidence from the brief that supports this hypothesis."
    )
    contradicting_or_limiting_evidence: list[str] = Field(
        description="Evidence that weakens or bounds this hypothesis."
    )
    evidence_needed: list[str] = Field(
        description="Evidence that would confirm or refute this hypothesis."
    )


class LikelyCause(BaseModel):
    leading_hypothesis: str | None = Field(
        description="The single best-supported hypothesis, or null if none stands out."
    )
    confidence: Confidence = Field(description="Confidence in the leading hypothesis.")
    reason: str = Field(description="Why this confidence level, grounded in the evidence.")


class NextAction(BaseModel):
    action: str = Field(description="A reversible check that can be safely undone.")
    expected_observation: str = Field(description="What you expect to see if a hypothesis holds.")
    risk_or_precondition: str = Field(description="Any risk or precondition before doing it.")


class Rollback(BaseModel):
    decision: RollbackDecision = Field(description="The rollback recommendation.")
    reason: str = Field(description="Justification tied to the evidence and confidence.")
    preconditions: list[str] = Field(
        description="Conditions that must hold for the decision (may be empty)."
    )


class IncidentAnalysis(BaseModel):
    """The full analysis contract. This is what 'a validated incident analysis'
    means in the milestone diagram."""

    known_facts: list[Fact]
    assumptions: list[Assumption]
    missing_information: list[MissingInfo]
    candidate_hypotheses: list[Hypothesis]
    likely_cause_assessment: LikelyCause
    reversible_next_actions: list[NextAction]
    rollback_recommendation: Rollback
    uncertainty_statement: str = Field(
        description="An honest statement of what remains unresolved."
    )


def _strictify(node: object) -> None:
    """Recursively enforce the API's strict-schema rules IN PLACE:
    every object must set additionalProperties=false and list all its
    properties as required. Pydantic's model_json_schema() omits both, so the
    raw output_config path needs this (messages.parse does it internally)."""
    if isinstance(node, dict):
        if node.get("type") == "object" and "properties" in node:
            node["additionalProperties"] = False
            node["required"] = list(node["properties"].keys())
        for value in node.values():
            _strictify(value)
    elif isinstance(node, list):
        for item in node:
            _strictify(item)


def strict_schema() -> dict:
    """The JSON Schema for IncidentAnalysis, made strict for output_config."""
    schema = IncidentAnalysis.model_json_schema()
    _strictify(schema)
    return schema
