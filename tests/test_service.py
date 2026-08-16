import pytest

from proto_virtual_lab.models import CampaignState, DesignSpecStatus
from proto_virtual_lab.seed import load_seeded_design_spec
from proto_virtual_lab.service import CampaignConflictError, CampaignService
from proto_virtual_lab.state_machine import InvalidStateTransitionError
from proto_virtual_lab.storage import CampaignRepository, ConcurrentUpdateError


def _campaign_with_spec(service: CampaignService) -> str:
    campaign = service.create_campaign("Test campaign", "Design a benign regulatory pair.", "tester")
    service.start_specification(campaign.id, "tester")
    design_spec = load_seeded_design_spec(campaign.id, "design_spec_test")
    service.put_design_spec(campaign.id, design_spec)
    return campaign.id


def test_campaign_and_spec_reload_from_fresh_repository(
    service: CampaignService,
    repository: CampaignRepository,
) -> None:
    campaign_id = _campaign_with_spec(service)
    reloaded_repository = CampaignRepository(repository.database_path, repository.artifact_root)

    campaign = reloaded_repository.get_campaign(campaign_id)
    design_spec = reloaded_repository.get_design_spec(campaign_id)

    assert campaign.state is CampaignState.SPEC_DRAFTING
    assert design_spec is not None
    assert design_spec.id == campaign.design_spec_id
    assert len(reloaded_repository.get_transitions(campaign_id)) == 2


def test_design_spec_approval_uses_required_gate(
    service: CampaignService,
    repository: CampaignRepository,
) -> None:
    campaign_id = _campaign_with_spec(service)

    with pytest.raises(CampaignConflictError, match="requires SPEC_AWAITING_APPROVAL"):
        service.approve_design_spec(campaign_id, "reviewer")

    submitted = service.submit_design_spec(campaign_id, "tester")
    approved = service.approve_design_spec(campaign_id, "reviewer")

    assert submitted.state is CampaignState.SPEC_AWAITING_APPROVAL
    assert approved.state is CampaignState.EVIDENCE_RETRIEVAL
    design_spec = repository.get_design_spec(campaign_id)
    assert design_spec is not None
    assert design_spec.status is DesignSpecStatus.APPROVED


def test_blocking_questions_prevent_approval(
    service: CampaignService,
    repository: CampaignRepository,
) -> None:
    campaign_id = _campaign_with_spec(service)
    design_spec = repository.get_design_spec(campaign_id)
    assert design_spec is not None
    blocked_spec = design_spec.model_copy(update={"blocking_questions": ["Choose a target operator."]})
    service.put_design_spec(campaign_id, blocked_spec)

    blocked = service.submit_design_spec(campaign_id, "tester")

    assert blocked.state is CampaignState.SPEC_BLOCKED
    with pytest.raises(CampaignConflictError, match="requires SPEC_AWAITING_APPROVAL"):
        service.approve_design_spec(campaign_id, "reviewer")


def test_invalid_state_transition_does_not_persist(service: CampaignService) -> None:
    campaign = service.create_campaign("Test", "Test goal", "tester")

    with pytest.raises(InvalidStateTransitionError):
        service.transition_campaign(
            campaign.id,
            CampaignState.READY_TO_RUN,
            "tester",
            "Attempt to bypass workflow.",
        )

    assert service.get_campaign(campaign.id).state is CampaignState.CREATED


def test_generic_transition_cannot_bypass_spec_approval(service: CampaignService) -> None:
    campaign_id = _campaign_with_spec(service)
    service.submit_design_spec(campaign_id, "tester")

    with pytest.raises(CampaignConflictError, match="dedicated approval gate"):
        service.transition_campaign(
            campaign_id,
            CampaignState.EVIDENCE_RETRIEVAL,
            "tester",
            "Attempt to bypass human approval.",
        )

    assert service.get_campaign(campaign_id).state is CampaignState.SPEC_AWAITING_APPROVAL


def test_material_revision_requires_ready_to_run(service: CampaignService) -> None:
    campaign = service.create_campaign("Test", "Test goal", "tester")

    with pytest.raises(CampaignConflictError, match="only available from READY_TO_RUN"):
        service.create_plan_revision(campaign.id, "tester", "Change objective.")


def test_stale_campaign_update_is_rejected(
    service: CampaignService,
    repository: CampaignRepository,
) -> None:
    campaign = service.create_campaign("Test", "Test goal", "tester")
    service.start_specification(campaign.id, "tester")
    stale_update = campaign.model_copy(update={"title": "Stale title"})

    with pytest.raises(ConcurrentUpdateError, match="changed before"):
        repository.commit_update(stale_update, expected_campaign=campaign)


def test_artifact_snapshots_are_written(
    service: CampaignService,
    repository: CampaignRepository,
) -> None:
    campaign_id = _campaign_with_spec(service)
    campaign_dir = repository.artifact_root / "campaigns" / campaign_id

    assert (campaign_dir / "campaign.json").is_file()
    assert (campaign_dir / "design_spec.json").is_file()
    assert len(list((campaign_dir / "design_specs").glob("*.json"))) == 1
    assert len(list((campaign_dir / "transitions").glob("*.json"))) == 2
    assert '"state": "SPEC_DRAFTING"' in (campaign_dir / "campaign.json").read_text(encoding="utf-8")


def test_design_spec_revisions_remain_immutable(
    service: CampaignService,
    repository: CampaignRepository,
) -> None:
    campaign_id = _campaign_with_spec(service)
    service.submit_design_spec(campaign_id, "tester")
    service.approve_design_spec(campaign_id, "reviewer")
    campaign = repository.get_campaign(campaign_id)
    revision_files = list((repository.artifact_root / "campaigns" / campaign_id / "design_specs").glob("*.json"))

    assert len(revision_files) == 3
    assert len({path.stem for path in revision_files}) == 3
    assert campaign.design_spec_id in {path.stem for path in revision_files}


def test_ready_campaign_revision_creates_linked_version(
    service: CampaignService,
    repository: CampaignRepository,
) -> None:
    campaign_id = _campaign_with_spec(service)
    campaign = repository.get_campaign(campaign_id)
    ready_campaign = campaign.model_copy(update={"state": CampaignState.READY_TO_RUN})
    repository.commit_update(ready_campaign)

    revision = service.create_plan_revision(campaign_id, "reviewer", "Material objective revision.")
    revision_spec = repository.get_design_spec(revision.id)

    assert revision.version == 2
    assert revision.parent_campaign_id == campaign_id
    assert revision.state is CampaignState.PLAN_REVISION
    assert repository.get_campaign(campaign_id).state is CampaignState.READY_TO_RUN
    assert revision_spec is not None
    assert revision_spec.id == revision.design_spec_id
    assert revision_spec.campaign_id == revision.id
    assert revision_spec.status is DesignSpecStatus.DRAFT
