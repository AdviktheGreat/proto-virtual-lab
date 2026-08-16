"""Campaign application service enforcing workflow invariants."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from proto_virtual_lab.models import (
    Campaign,
    CampaignState,
    DesignSpec,
    DesignSpecStatus,
    StateTransition,
)
from proto_virtual_lab.state_machine import InvalidStateTransitionError, ensure_transition_allowed
from proto_virtual_lab.storage import CampaignRepository


class CampaignConflictError(ValueError):
    """Raised when an operation conflicts with campaign state or ownership."""


class CampaignService:
    """Coordinate typed campaign artifacts and deterministic transitions."""

    _APPROVAL_GATED_TRANSITIONS = frozenset(
        {
            (CampaignState.SPEC_AWAITING_APPROVAL, CampaignState.EVIDENCE_RETRIEVAL),
            (CampaignState.PLAN_AWAITING_APPROVAL, CampaignState.COMPILING),
        }
    )

    def __init__(self, repository: CampaignRepository) -> None:
        self.repository = repository

    def create_campaign(self, title: str, user_goal: str, actor: str) -> Campaign:
        now = self._now()
        campaign = Campaign(
            id=self._id("campaign"),
            version=1,
            title=title,
            created_at=now,
            updated_at=now,
            state=CampaignState.CREATED,
            user_goal=user_goal,
        )
        transition = self._transition_record(
            campaign=campaign,
            previous_state=None,
            next_state=CampaignState.CREATED,
            actor=actor,
            reason="Campaign created.",
        )
        self.repository.create_campaign(campaign, transition)
        return campaign

    def get_campaign(self, campaign_id: str) -> Campaign:
        return self.repository.get_campaign(campaign_id)

    def start_specification(self, campaign_id: str, actor: str) -> Campaign:
        return self.transition_campaign(
            campaign_id,
            CampaignState.SPEC_DRAFTING,
            actor,
            "Specification drafting started.",
        )

    def put_design_spec(self, campaign_id: str, design_spec: DesignSpec) -> Campaign:
        campaign = self.repository.get_campaign(campaign_id)
        if campaign.state not in {CampaignState.SPEC_DRAFTING, CampaignState.SPEC_BLOCKED}:
            raise CampaignConflictError("DesignSpec can only be edited while specification drafting is active")
        if design_spec.campaign_id != campaign_id:
            raise CampaignConflictError("DesignSpec campaign_id does not match the target campaign")
        if design_spec.status is DesignSpecStatus.APPROVED:
            raise CampaignConflictError("DesignSpec approval must use the approval gate")

        current_spec = self.repository.get_design_spec(campaign_id)
        if current_spec is not None and design_spec.id == current_spec.id:
            design_spec = design_spec.model_copy(update={"id": self._id("design_spec")})
        now = self._now()
        updated = campaign.model_copy(
            update={
                "design_spec_id": design_spec.id,
                "updated_at": now,
                "state": CampaignState.SPEC_DRAFTING,
            }
        )
        transition: StateTransition | None = None
        if campaign.state is CampaignState.SPEC_BLOCKED:
            ensure_transition_allowed(campaign.state, CampaignState.SPEC_DRAFTING)
            transition = self._transition_record(
                updated,
                campaign.state,
                CampaignState.SPEC_DRAFTING,
                "system",
                "Blocking questions are being revised.",
                [design_spec.id],
            )
        self.repository.commit_update(
            updated,
            transition=transition,
            design_spec=design_spec,
            expected_campaign=campaign,
        )
        return updated

    def submit_design_spec(self, campaign_id: str, actor: str) -> Campaign:
        campaign = self.repository.get_campaign(campaign_id)
        if campaign.state is not CampaignState.SPEC_DRAFTING:
            raise CampaignConflictError("DesignSpec can only be submitted from SPEC_DRAFTING")
        design_spec = self._require_design_spec(campaign_id)

        if design_spec.blocking_questions:
            next_state = CampaignState.SPEC_BLOCKED
            status = DesignSpecStatus.BLOCKED
            reason = "DesignSpec has unresolved blocking questions."
        else:
            next_state = CampaignState.SPEC_AWAITING_APPROVAL
            status = DesignSpecStatus.DRAFT
            reason = "DesignSpec submitted for human approval."

        updated_spec = design_spec.model_copy(update={"id": self._id("design_spec"), "status": status})
        return self._transition_with_spec(campaign, next_state, actor, reason, updated_spec)

    def approve_design_spec(self, campaign_id: str, actor: str) -> Campaign:
        campaign = self.repository.get_campaign(campaign_id)
        if campaign.state is not CampaignState.SPEC_AWAITING_APPROVAL:
            raise CampaignConflictError("DesignSpec approval requires SPEC_AWAITING_APPROVAL")
        design_spec = self._require_design_spec(campaign_id)
        if design_spec.blocking_questions:
            raise CampaignConflictError("DesignSpec cannot be approved while blocking questions remain")

        approved_spec = design_spec.model_copy(
            update={
                "id": self._id("design_spec"),
                "status": DesignSpecStatus.APPROVED,
            }
        )
        return self._transition_with_spec(
            campaign,
            CampaignState.EVIDENCE_RETRIEVAL,
            actor,
            "Human approved the DesignSpec.",
            approved_spec,
        )

    def transition_campaign(
        self,
        campaign_id: str,
        next_state: CampaignState,
        actor: str,
        reason: str,
        artifact_refs: list[str] | None = None,
    ) -> Campaign:
        campaign = self.repository.get_campaign(campaign_id)
        if (campaign.state, next_state) in self._APPROVAL_GATED_TRANSITIONS:
            raise CampaignConflictError(
                f"transition from {campaign.state} to {next_state} requires its dedicated approval gate"
            )
        ensure_transition_allowed(campaign.state, next_state)
        now = self._now()
        updated = campaign.model_copy(update={"state": next_state, "updated_at": now})
        transition = self._transition_record(
            campaign=updated,
            previous_state=campaign.state,
            next_state=next_state,
            actor=actor,
            reason=reason,
            artifact_refs=artifact_refs,
        )
        self.repository.commit_update(updated, transition=transition, expected_campaign=campaign)
        return updated

    def create_plan_revision(self, campaign_id: str, actor: str, reason: str) -> Campaign:
        """Create a new campaign version for a material post-validation revision."""

        parent = self.repository.get_campaign(campaign_id)
        if parent.state is not CampaignState.READY_TO_RUN:
            raise CampaignConflictError("material versioning is only available from READY_TO_RUN")
        ensure_transition_allowed(parent.state, CampaignState.PLAN_REVISION)

        now = self._now()
        revision_id = self._id("campaign")
        parent_spec = self.repository.get_design_spec(parent.id)
        revision_spec = (
            parent_spec.model_copy(
                update={
                    "id": self._id("design_spec"),
                    "campaign_id": revision_id,
                    "status": DesignSpecStatus.DRAFT,
                }
            )
            if parent_spec is not None
            else None
        )
        revision = Campaign(
            id=revision_id,
            version=parent.version + 1,
            title=parent.title,
            created_at=now,
            updated_at=now,
            state=CampaignState.PLAN_REVISION,
            user_goal=parent.user_goal,
            design_spec_id=revision_spec.id if revision_spec is not None else None,
            program_plan_id=parent.program_plan_id,
            parent_campaign_id=parent.id,
        )
        transition = self._transition_record(
            revision,
            parent.state,
            CampaignState.PLAN_REVISION,
            actor,
            reason,
            [value for value in (revision.design_spec_id, parent.program_plan_id) if value is not None],
        )
        self.repository.create_campaign(revision, transition, revision_spec)
        return revision

    def _transition_with_spec(
        self,
        campaign: Campaign,
        next_state: CampaignState,
        actor: str,
        reason: str,
        design_spec: DesignSpec,
    ) -> Campaign:
        ensure_transition_allowed(campaign.state, next_state)
        updated = campaign.model_copy(
            update={
                "design_spec_id": design_spec.id,
                "state": next_state,
                "updated_at": self._now(),
            }
        )
        transition = self._transition_record(
            updated,
            campaign.state,
            next_state,
            actor,
            reason,
            [design_spec.id],
        )
        self.repository.commit_update(
            updated,
            transition=transition,
            design_spec=design_spec,
            expected_campaign=campaign,
        )
        return updated

    def _require_design_spec(self, campaign_id: str) -> DesignSpec:
        design_spec = self.repository.get_design_spec(campaign_id)
        if design_spec is None:
            raise CampaignConflictError("campaign has no DesignSpec")
        return design_spec

    @staticmethod
    def _transition_record(
        campaign: Campaign,
        previous_state: CampaignState | None,
        next_state: CampaignState,
        actor: str,
        reason: str,
        artifact_refs: list[str] | None = None,
    ) -> StateTransition:
        return StateTransition(
            id=CampaignService._id("transition"),
            campaign_id=campaign.id,
            campaign_version=campaign.version,
            previous_state=previous_state,
            next_state=next_state,
            triggering_actor=actor,
            timestamp=campaign.updated_at,
            artifact_refs=artifact_refs or [],
            reason=reason,
        )

    @staticmethod
    def _now() -> datetime:
        return datetime.now(UTC)

    @staticmethod
    def _id(prefix: str) -> str:
        return f"{prefix}_{uuid4().hex}"


__all__ = ["CampaignConflictError", "CampaignService", "InvalidStateTransitionError"]
