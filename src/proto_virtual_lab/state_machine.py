"""Deterministic campaign transition policy."""

from __future__ import annotations

from collections.abc import Mapping

from proto_virtual_lab.models import CampaignState


class InvalidStateTransitionError(ValueError):
    """Raised when a requested campaign transition is not permitted."""


ALLOWED_TRANSITIONS: Mapping[CampaignState, frozenset[CampaignState]] = {
    CampaignState.CREATED: frozenset({CampaignState.SPEC_DRAFTING, CampaignState.CANCELLED}),
    CampaignState.SPEC_DRAFTING: frozenset(
        {CampaignState.SPEC_BLOCKED, CampaignState.SPEC_AWAITING_APPROVAL, CampaignState.CANCELLED}
    ),
    CampaignState.SPEC_BLOCKED: frozenset({CampaignState.SPEC_DRAFTING, CampaignState.CANCELLED}),
    CampaignState.SPEC_AWAITING_APPROVAL: frozenset(
        {CampaignState.SPEC_DRAFTING, CampaignState.EVIDENCE_RETRIEVAL, CampaignState.CANCELLED}
    ),
    CampaignState.EVIDENCE_RETRIEVAL: frozenset({CampaignState.CAPABILITY_DISCOVERY, CampaignState.CANCELLED}),
    CampaignState.CAPABILITY_DISCOVERY: frozenset({CampaignState.TEAM_DELIBERATION, CampaignState.CANCELLED}),
    CampaignState.TEAM_DELIBERATION: frozenset({CampaignState.PROGRAM_PLAN_DRAFTED, CampaignState.CANCELLED}),
    CampaignState.PROGRAM_PLAN_DRAFTED: frozenset({CampaignState.CRITIC_REVIEW, CampaignState.CANCELLED}),
    CampaignState.CRITIC_REVIEW: frozenset(
        {CampaignState.PLAN_REVISION, CampaignState.PLAN_AWAITING_APPROVAL, CampaignState.CANCELLED}
    ),
    CampaignState.PLAN_REVISION: frozenset({CampaignState.TEAM_DELIBERATION, CampaignState.CANCELLED}),
    CampaignState.PLAN_AWAITING_APPROVAL: frozenset(
        {CampaignState.PLAN_REVISION, CampaignState.COMPILING, CampaignState.CANCELLED}
    ),
    CampaignState.COMPILING: frozenset({CampaignState.VALIDATING_PROGRAM, CampaignState.CANCELLED}),
    CampaignState.VALIDATING_PROGRAM: frozenset(
        {CampaignState.READY_TO_RUN, CampaignState.PLAN_REVISION, CampaignState.CANCELLED}
    ),
    CampaignState.READY_TO_RUN: frozenset(
        {CampaignState.RUNNING, CampaignState.PLAN_REVISION, CampaignState.CANCELLED}
    ),
    CampaignState.RUNNING: frozenset({CampaignState.RUN_FAILED, CampaignState.ANALYZING_RUN, CampaignState.CANCELLED}),
    CampaignState.RUN_FAILED: frozenset(
        {CampaignState.READY_TO_RUN, CampaignState.PLAN_REVISION, CampaignState.CANCELLED}
    ),
    CampaignState.ANALYZING_RUN: frozenset(
        {CampaignState.REPORTING, CampaignState.RUN_FAILED, CampaignState.CANCELLED}
    ),
    CampaignState.REPORTING: frozenset({CampaignState.COMPLETED, CampaignState.RUN_FAILED, CampaignState.CANCELLED}),
    CampaignState.COMPLETED: frozenset(),
    CampaignState.CANCELLED: frozenset(),
}


def ensure_transition_allowed(previous: CampaignState, next_state: CampaignState) -> None:
    """Raise unless ``next_state`` is an explicit successor of ``previous``."""

    if next_state not in ALLOWED_TRANSITIONS[previous]:
        raise InvalidStateTransitionError(f"transition from {previous} to {next_state} is not allowed")
