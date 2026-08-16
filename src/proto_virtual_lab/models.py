"""Strict, persisted contracts for the Proto Virtual Lab workflow."""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, StrictBool, model_validator

NonEmptyString = Annotated[str, Field(min_length=1)]
ArtifactId = Annotated[
    str,
    Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$"),
]
PositiveInt = Annotated[int, Field(strict=True, gt=0)]
StrictFloat = Annotated[float, Field(strict=True)]
NonNegativeFloat = Annotated[float, Field(strict=True, ge=0)]
JsonObject = dict[str, Any]


class StrictModel(BaseModel):
    """Base contract that rejects unknown fields and mutation."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class CampaignState(StrEnum):
    """Persisted lifecycle states from the authoritative product specification."""

    CREATED = "CREATED"
    SPEC_DRAFTING = "SPEC_DRAFTING"
    SPEC_BLOCKED = "SPEC_BLOCKED"
    SPEC_AWAITING_APPROVAL = "SPEC_AWAITING_APPROVAL"
    EVIDENCE_RETRIEVAL = "EVIDENCE_RETRIEVAL"
    CAPABILITY_DISCOVERY = "CAPABILITY_DISCOVERY"
    TEAM_DELIBERATION = "TEAM_DELIBERATION"
    PROGRAM_PLAN_DRAFTED = "PROGRAM_PLAN_DRAFTED"
    CRITIC_REVIEW = "CRITIC_REVIEW"
    PLAN_REVISION = "PLAN_REVISION"
    PLAN_AWAITING_APPROVAL = "PLAN_AWAITING_APPROVAL"
    COMPILING = "COMPILING"
    VALIDATING_PROGRAM = "VALIDATING_PROGRAM"
    READY_TO_RUN = "READY_TO_RUN"
    RUNNING = "RUNNING"
    RUN_FAILED = "RUN_FAILED"
    ANALYZING_RUN = "ANALYZING_RUN"
    REPORTING = "REPORTING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class Modality(StrEnum):
    DNA = "dna"
    RNA = "rna"
    PROTEIN = "protein"
    LIGAND = "ligand"
    MULTIMODAL = "multimodal"


class SequenceType(StrEnum):
    DNA = "dna"
    RNA = "rna"
    PROTEIN = "protein"
    LIGAND = "ligand"


class Priority(StrEnum):
    MUST = "must"
    SHOULD = "should"
    EXPLORATORY = "exploratory"


class DesignSpecStatus(StrEnum):
    DRAFT = "draft"
    BLOCKED = "blocked"
    APPROVED = "approved"


class ProgramPlanStatus(StrEnum):
    DRAFT = "draft"
    IN_REVIEW = "in_review"
    REVISION_REQUIRED = "revision_required"
    APPROVED = "approved"


class ComponentType(StrEnum):
    GENERATOR = "generator"
    CONSTRAINT = "constraint"
    OPTIMIZER = "optimizer"


class ComputeClass(StrEnum):
    DETERMINISTIC = "deterministic"
    CHEAP = "cheap"
    MODERATE = "moderate"
    EXPENSIVE = "expensive"


class ConstraintRole(StrEnum):
    FILTER = "filter"
    STEERING = "steering"
    RANKER = "ranker"
    VALIDATOR = "validator"


class ObjectionSeverity(StrEnum):
    BLOCKING = "blocking"
    MAJOR = "major"
    MINOR = "minor"


class ObjectionResolutionStatus(StrEnum):
    OPEN = "open"
    REVISED = "revised"
    REBUTTED = "rebutted"
    ACCEPTED_LIMITATION = "accepted_limitation"


class EvidenceSourceType(StrEnum):
    PRIMARY_PAPER = "primary_paper"
    PREPRINT = "preprint"
    OFFICIAL_DOCS = "official_docs"
    DATASET = "dataset"
    DATABASE = "database"


class EvidenceApplicability(StrEnum):
    DIRECT = "direct"
    PARTIAL = "partial"
    ADJACENT = "adjacent"
    UNCERTAIN = "uncertain"


class EvidenceDisposition(StrEnum):
    SUPPORTS = "supports"
    CHALLENGES = "challenges"
    CONTEXTUAL = "contextual"


class RunEventSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class CompiledProgramStatus(StrEnum):
    INVALID = "invalid"
    VALID = "valid"
    EXECUTED = "executed"


class Campaign(StrictModel):
    id: ArtifactId
    version: Annotated[int, Field(strict=True, ge=1)]
    title: NonEmptyString
    created_at: datetime
    updated_at: datetime
    state: CampaignState
    user_goal: NonEmptyString
    design_spec_id: ArtifactId | None = None
    program_plan_id: ArtifactId | None = None
    compiled_program_id: ArtifactId | None = None
    proto_run_id: ArtifactId | None = None
    validation_dossier_id: ArtifactId | None = None
    parent_campaign_id: ArtifactId | None = None


class LengthBoundedModel(StrictModel):
    """Shared contract for entities whose sequence length may be bounded."""

    length_bounds: tuple[PositiveInt, PositiveInt] | None = None

    @model_validator(mode="after")
    def validate_length_bounds(self) -> LengthBoundedModel:
        if self.length_bounds is not None and self.length_bounds[0] > self.length_bounds[1]:
            raise ValueError("length_bounds minimum cannot exceed maximum")
        return self


class DesignedEntity(LengthBoundedModel):
    name: NonEmptyString
    sequence_type: SequenceType
    mutable: StrictBool
    fixed_assets: list[NonEmptyString] = Field(default_factory=list)


class SuccessCriterion(StrictModel):
    id: NonEmptyString
    statement: NonEmptyString
    measurement_type: NonEmptyString
    priority: Priority


class ComputeBudget(StrictModel):
    max_cost_usd: NonNegativeFloat | None = None
    max_cpu_hours: NonNegativeFloat | None = None
    max_gpu_hours: NonNegativeFloat | None = None


class TimeBudget(StrictModel):
    max_wall_clock_minutes: PositiveInt
    deadline: datetime | None = None


class DesignSpec(StrictModel):
    id: ArtifactId
    campaign_id: ArtifactId
    modality: list[Modality] = Field(min_length=1)
    objective_summary: NonEmptyString
    designed_entities: list[DesignedEntity] = Field(min_length=1)
    target_contexts: list[NonEmptyString] = Field(default_factory=list)
    off_target_contexts: list[NonEmptyString] = Field(default_factory=list)
    success_criteria: list[SuccessCriterion] = Field(min_length=1)
    negative_criteria: list[NonEmptyString] = Field(default_factory=list)
    failure_conditions: list[NonEmptyString] = Field(default_factory=list)
    required_inputs: list[NonEmptyString] = Field(default_factory=list)
    compute_budget: ComputeBudget
    time_budget: TimeBudget
    requested_candidate_count: PositiveInt
    assumptions: list[NonEmptyString] = Field(default_factory=list)
    blocking_questions: list[NonEmptyString] = Field(default_factory=list)
    status: DesignSpecStatus

    @model_validator(mode="after")
    def validate_status(self) -> DesignSpec:
        if self.status is DesignSpecStatus.APPROVED and self.blocking_questions:
            raise ValueError("an approved DesignSpec cannot have blocking questions")
        if self.status is DesignSpecStatus.BLOCKED and not self.blocking_questions:
            raise ValueError("a blocked DesignSpec must identify at least one blocking question")
        return self


class EvidenceRecord(StrictModel):
    id: NonEmptyString
    campaign_id: NonEmptyString
    requirement_ids: list[NonEmptyString] = Field(min_length=1)
    claim: NonEmptyString
    source_title: NonEmptyString
    source_url: AnyHttpUrl
    doi_or_identifier: str | None = None
    source_type: EvidenceSourceType
    publication_date: date | None = None
    retrieved_at: datetime
    evidence_excerpt_or_summary: NonEmptyString
    biological_system: NonEmptyString
    measurement: NonEmptyString
    applicability: EvidenceApplicability
    limitations: list[NonEmptyString] = Field(default_factory=list)
    supports_or_challenges: EvidenceDisposition
    paperclip_document_id: str | None = None


class ProtoComponentCandidate(StrictModel):
    registry_key: NonEmptyString
    component_type: ComponentType
    source_module: NonEmptyString
    version_or_commit: NonEmptyString
    config_schema: JsonObject
    required_inputs: list[NonEmptyString] = Field(default_factory=list)
    outputs: list[NonEmptyString] = Field(default_factory=list)
    compute_class: ComputeClass
    gradient_capable: StrictBool
    credential_requirements: list[NonEmptyString] = Field(default_factory=list)
    mapped_requirement_ids: list[NonEmptyString] = Field(default_factory=list)
    rationale: NonEmptyString
    evidence_record_ids: list[NonEmptyString] = Field(default_factory=list)
    limitations: list[NonEmptyString] = Field(default_factory=list)


class SegmentPlan(LengthBoundedModel):
    id: NonEmptyString
    sequence_type: SequenceType
    mutable: StrictBool


class ConstructPlan(StrictModel):
    id: NonEmptyString
    segment_ids: list[NonEmptyString] = Field(min_length=1)


class ComponentReference(StrictModel):
    registry_key: NonEmptyString
    config: JsonObject = Field(default_factory=dict)


class PlannedConstraint(StrictModel):
    component: ComponentReference
    role: ConstraintRole
    weight: StrictFloat | None = None
    threshold: StrictFloat | None = None
    mapped_requirement_ids: list[NonEmptyString] = Field(min_length=1)


class ProgramStage(StrictModel):
    id: NonEmptyString
    order: Annotated[int, Field(strict=True, ge=1)]
    purpose: NonEmptyString
    target_segments: list[NonEmptyString] = Field(min_length=1)
    generator: ComponentReference
    constraints: list[PlannedConstraint] = Field(min_length=1)
    optimizer: ComponentReference
    input_candidate_count: PositiveInt | None = None
    output_candidate_count: PositiveInt | None = None
    compute_estimate: JsonObject = Field(default_factory=dict)


class ProgramPlan(StrictModel):
    id: NonEmptyString
    campaign_id: NonEmptyString
    proto_commit: NonEmptyString
    segments: list[SegmentPlan] = Field(min_length=1)
    constructs: list[ConstructPlan] = Field(min_length=1)
    stages: list[ProgramStage] = Field(min_length=1)
    validation_panel: list[JsonObject] = Field(default_factory=list)
    unmeasured_requirements: list[NonEmptyString] = Field(default_factory=list)
    assumptions: list[NonEmptyString] = Field(default_factory=list)
    known_limitations: list[NonEmptyString] = Field(default_factory=list)
    status: ProgramPlanStatus

    @model_validator(mode="after")
    def validate_stage_order(self) -> ProgramPlan:
        orders = [stage.order for stage in self.stages]
        if sorted(orders) != list(range(1, len(orders) + 1)):
            raise ValueError("stage order must be contiguous and start at 1")
        return self


class CriticObjection(StrictModel):
    id: NonEmptyString
    campaign_id: NonEmptyString
    program_plan_id: NonEmptyString
    category: NonEmptyString
    severity: ObjectionSeverity
    statement: NonEmptyString
    affected_requirement_ids: list[NonEmptyString] = Field(min_length=1)
    evidence_record_ids: list[NonEmptyString] = Field(default_factory=list)
    failure_scenario: NonEmptyString
    requested_resolution: NonEmptyString
    resolution_status: ObjectionResolutionStatus
    resolution_text: str | None = None
    resolved_by: str | None = None
    resolved_at: datetime | None = None

    @model_validator(mode="after")
    def validate_resolution(self) -> CriticObjection:
        resolution_fields = (self.resolution_text, self.resolved_by, self.resolved_at)
        if self.resolution_status is ObjectionResolutionStatus.OPEN and any(resolution_fields):
            raise ValueError("open objections cannot contain resolution metadata")
        if self.resolution_status is not ObjectionResolutionStatus.OPEN and not all(resolution_fields):
            raise ValueError("resolved objections require text, actor, and timestamp")
        return self


class CompiledProgram(StrictModel):
    id: NonEmptyString
    campaign_id: NonEmptyString
    program_plan_id: NonEmptyString
    language: Literal["python"]
    source_path: NonEmptyString
    source_hash: NonEmptyString
    proto_commit: NonEmptyString
    generated_at: datetime
    validation_checks: list[JsonObject] = Field(default_factory=list)
    status: CompiledProgramStatus


class RunEvent(StrictModel):
    id: NonEmptyString
    campaign_id: NonEmptyString
    run_id: NonEmptyString
    timestamp: datetime
    event_type: NonEmptyString
    stage_id: str | None = None
    severity: RunEventSeverity
    message: NonEmptyString
    metrics: JsonObject = Field(default_factory=dict)
    artifact_refs: list[NonEmptyString] = Field(default_factory=list)


class ValidationDossier(StrictModel):
    id: NonEmptyString
    campaign_id: NonEmptyString
    candidate_reports: list[JsonObject]
    validation_level: Annotated[int, Field(strict=True, ge=0, le=4)]
    level_rationale: NonEmptyString
    in_loop_evidence: list[JsonObject] = Field(default_factory=list)
    orthogonal_evidence: list[JsonObject] = Field(default_factory=list)
    published_calibration: JsonObject | None = None
    experimental_evidence: JsonObject | None = None
    novelty_checks: list[JsonObject] = Field(default_factory=list)
    sanity_checks: list[JsonObject] = Field(default_factory=list)
    unsupported_claims: list[NonEmptyString] = Field(default_factory=list)
    limitations: list[NonEmptyString] = Field(default_factory=list)
    recommended_next_experiments: list[NonEmptyString] = Field(default_factory=list)
    final_claim_text: NonEmptyString


class StateTransition(StrictModel):
    id: ArtifactId
    campaign_id: ArtifactId
    campaign_version: Annotated[int, Field(strict=True, ge=1)]
    previous_state: CampaignState | None
    next_state: CampaignState
    triggering_actor: NonEmptyString
    timestamp: datetime
    artifact_refs: list[NonEmptyString] = Field(default_factory=list)
    reason: NonEmptyString
    error_data: JsonObject | None = None
