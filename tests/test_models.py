from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from proto_virtual_lab.models import (
    DesignedEntity,
    DesignSpec,
    DesignSpecStatus,
    ObjectionResolutionStatus,
    ObjectionSeverity,
    SegmentPlan,
    SequenceType,
    StateTransition,
)
from proto_virtual_lab.seed import load_seeded_design_spec


def test_seeded_design_spec_is_valid() -> None:
    design_spec = load_seeded_design_spec("campaign_test", "design_spec_test")

    assert design_spec.campaign_id == "campaign_test"
    assert design_spec.status is DesignSpecStatus.DRAFT
    assert len(design_spec.success_criteria) == 7


def test_unknown_fields_are_rejected() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        StateTransition(
            id="transition_test",
            campaign_id="campaign_test",
            campaign_version=1,
            previous_state=None,
            next_state="CREATED",
            triggering_actor="test",
            timestamp=datetime.now(UTC),
            artifact_refs=[],
            reason="Created",
            unexpected=True,
        )


def test_invalid_length_bounds_are_rejected() -> None:
    with pytest.raises(ValidationError, match="minimum cannot exceed maximum"):
        DesignedEntity(
            name="bad",
            sequence_type=SequenceType.DNA,
            mutable=True,
            length_bounds=(100, 80),
        )


def test_invalid_segment_length_bounds_are_rejected() -> None:
    with pytest.raises(ValidationError, match="minimum cannot exceed maximum"):
        SegmentPlan(
            id="segment_bad",
            sequence_type=SequenceType.PROTEIN,
            mutable=True,
            length_bounds=(200, 80),
        )


def test_approved_design_spec_cannot_keep_blocking_questions() -> None:
    design_spec = load_seeded_design_spec("campaign_test", "design_spec_test")
    invalid_data = design_spec.model_dump()
    invalid_data.update(
        {
            "status": DesignSpecStatus.APPROVED,
            "blocking_questions": ["Which target should be used?"],
        }
    )

    with pytest.raises(ValidationError, match="cannot have blocking questions"):
        DesignSpec.model_validate(invalid_data)


def test_numeric_strings_are_not_coerced() -> None:
    design_spec = load_seeded_design_spec("campaign_test", "design_spec_test")
    invalid_data = design_spec.model_dump()
    invalid_data["requested_candidate_count"] = "8"

    with pytest.raises(ValidationError, match="valid integer"):
        DesignSpec.model_validate(invalid_data)


def test_artifact_identifiers_cannot_escape_storage_paths() -> None:
    design_spec = load_seeded_design_spec("campaign_test", "design_spec_test")
    invalid_data = design_spec.model_dump()
    invalid_data["id"] = "../../outside"

    with pytest.raises(ValidationError, match="String should match pattern"):
        DesignSpec.model_validate(invalid_data)


def test_resolved_objection_requires_complete_resolution_metadata() -> None:
    from proto_virtual_lab.models import CriticObjection

    with pytest.raises(ValidationError, match="require text, actor, and timestamp"):
        CriticObjection(
            id="objection_test",
            campaign_id="campaign_test",
            program_plan_id="plan_test",
            category="coverage",
            severity=ObjectionSeverity.BLOCKING,
            statement="A requirement is unmapped.",
            affected_requirement_ids=["REQ-1"],
            failure_scenario="The plan compiles without the requirement.",
            requested_resolution="Map or mark the requirement unmeasured.",
            resolution_status=ObjectionResolutionStatus.REVISED,
        )
