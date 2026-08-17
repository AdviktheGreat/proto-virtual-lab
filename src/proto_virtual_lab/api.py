"""FastAPI surface for Milestone 1 campaign contracts."""

from typing import Annotated

from fastapi import Depends, FastAPI, Header, Query, Request, status
from fastapi.responses import JSONResponse
from pydantic import Field

from proto_virtual_lab.capabilities import CapabilityIntrospector, ProtoComponentNotFoundError
from proto_virtual_lab.models import (
    Campaign,
    CapabilityCatalog,
    ComponentType,
    DesignSpec,
    ProtoComponentCandidate,
    ProtoSmokeRequest,
    ProtoSmokeRun,
    ReproducibilityManifest,
    StateTransition,
    StrictModel,
)
from proto_virtual_lab.proto_revisions import ProtoRevisionMismatchError, require_pinned_proto
from proto_virtual_lab.proto_smoke import (
    ProtoSmokeBusyError,
    ProtoSmokeExecutionError,
    ProtoSmokeRunner,
    ProtoSmokeRunNotFoundError,
)
from proto_virtual_lab.seed import load_seeded_design_spec
from proto_virtual_lab.service import CampaignConflictError, CampaignService
from proto_virtual_lab.settings import Settings
from proto_virtual_lab.state_machine import InvalidStateTransitionError
from proto_virtual_lab.storage import (
    CampaignRepository,
    ConcurrentUpdateError,
    DuplicateRecordError,
    RecordNotFoundError,
)

Actor = Annotated[str, Header(alias="X-Actor", min_length=1)]


class CreateCampaignRequest(StrictModel):
    title: Annotated[str, Field(min_length=1)]
    user_goal: Annotated[str, Field(min_length=1)]


class CampaignView(StrictModel):
    campaign: Campaign
    design_spec: DesignSpec | None
    state_transitions: list[StateTransition]


class ErrorResponse(StrictModel):
    error: str
    detail: str


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build an application with explicitly configured local persistence."""

    resolved_settings = settings or Settings()
    repository = CampaignRepository(resolved_settings.database_path, resolved_settings.artifact_root)
    repository.initialize()
    service = CampaignService(repository)
    capability_introspector = CapabilityIntrospector()
    proto_smoke_runner = ProtoSmokeRunner(resolved_settings.artifact_root)

    app = FastAPI(
        title="Proto Virtual Lab",
        version="0.1.0",
        description="Typed, auditable scientific campaign control plane for Proto.",
    )
    app.state.repository = repository
    app.state.service = service
    app.state.capability_introspector = capability_introspector
    app.state.proto_smoke_runner = proto_smoke_runner

    def get_repository() -> CampaignRepository:
        return repository

    def get_service() -> CampaignService:
        return service

    def get_capability_introspector() -> CapabilityIntrospector:
        return capability_introspector

    def get_proto_smoke_runner() -> ProtoSmokeRunner:
        return proto_smoke_runner

    @app.exception_handler(RecordNotFoundError)
    @app.exception_handler(ProtoComponentNotFoundError)
    @app.exception_handler(ProtoSmokeRunNotFoundError)
    async def not_found_handler(_request: Request, error: LookupError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content=ErrorResponse(error="not_found", detail=str(error)).model_dump(),
        )

    @app.exception_handler(CampaignConflictError)
    @app.exception_handler(InvalidStateTransitionError)
    @app.exception_handler(DuplicateRecordError)
    @app.exception_handler(ConcurrentUpdateError)
    async def conflict_handler(_request: Request, error: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content=ErrorResponse(error="campaign_conflict", detail=str(error)).model_dump(),
        )

    @app.exception_handler(ProtoRevisionMismatchError)
    async def proto_revision_handler(_request: Request, error: ProtoRevisionMismatchError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=ErrorResponse(error="proto_revision_mismatch", detail=str(error)).model_dump(),
        )

    @app.exception_handler(ProtoSmokeExecutionError)
    async def proto_execution_handler(_request: Request, error: ProtoSmokeExecutionError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=ErrorResponse(error="proto_execution", detail=str(error)).model_dump(),
        )

    @app.exception_handler(ProtoSmokeBusyError)
    async def proto_busy_handler(_request: Request, error: ProtoSmokeBusyError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content=ErrorResponse(error="proto_busy", detail=str(error)).model_dump(),
        )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/proto/manifest", response_model=ReproducibilityManifest)
    def get_proto_manifest() -> ReproducibilityManifest:
        return require_pinned_proto()

    @app.get("/proto/capabilities", response_model=CapabilityCatalog)
    def list_proto_capabilities(
        introspector: Annotated[CapabilityIntrospector, Depends(get_capability_introspector)],
    ) -> CapabilityCatalog:
        return introspector.discover()

    @app.get(
        "/proto/capabilities/{component_type}/{registry_key}",
        response_model=ProtoComponentCandidate,
    )
    def get_proto_capability(
        component_type: ComponentType,
        registry_key: str,
        introspector: Annotated[CapabilityIntrospector, Depends(get_capability_introspector)],
    ) -> ProtoComponentCandidate:
        return introspector.get(component_type, registry_key)

    @app.post("/proto/smoke", response_model=ProtoSmokeRun, status_code=status.HTTP_201_CREATED)
    def run_proto_smoke(
        request: ProtoSmokeRequest,
        runner: Annotated[ProtoSmokeRunner, Depends(get_proto_smoke_runner)],
    ) -> ProtoSmokeRun:
        return runner.run(request)

    @app.get("/proto/smoke/{run_id}", response_model=ProtoSmokeRun)
    def get_proto_smoke(
        run_id: str,
        runner: Annotated[ProtoSmokeRunner, Depends(get_proto_smoke_runner)],
    ) -> ProtoSmokeRun:
        return runner.get(run_id)

    @app.post("/campaigns", response_model=CampaignView, status_code=status.HTTP_201_CREATED)
    def create_campaign(
        payload: CreateCampaignRequest,
        campaign_service: Annotated[CampaignService, Depends(get_service)],
        campaign_repository: Annotated[CampaignRepository, Depends(get_repository)],
        actor: Actor = "human:user",
    ) -> CampaignView:
        campaign = campaign_service.create_campaign(payload.title, payload.user_goal, actor)
        return _view(campaign.id, campaign_repository)

    @app.post("/campaigns/seeded", response_model=CampaignView, status_code=status.HTTP_201_CREATED)
    def create_seeded_campaign(
        campaign_service: Annotated[CampaignService, Depends(get_service)],
        campaign_repository: Annotated[CampaignRepository, Depends(get_repository)],
        actor: Actor = "human:user",
    ) -> CampaignView:
        campaign = campaign_service.create_campaign(
            title="Synthetic promoter-repressor design",
            user_goal=(
                "Computationally nominate a synthetic promoter-repressor pair with predicted promoter activity, "
                "cognate protein-DNA binding, and reduced predicted off-target interactions."
            ),
            actor=actor,
        )
        campaign_service.start_specification(campaign.id, actor)
        design_spec = load_seeded_design_spec(campaign.id, f"design_spec_{campaign.id.removeprefix('campaign_')}")
        campaign_service.put_design_spec(campaign.id, design_spec)
        campaign_service.submit_design_spec(campaign.id, actor)
        return _view(campaign.id, campaign_repository)

    @app.get("/campaigns", response_model=list[Campaign])
    def list_campaigns(
        campaign_repository: Annotated[CampaignRepository, Depends(get_repository)],
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> list[Campaign]:
        return campaign_repository.list_campaigns(limit=limit, offset=offset)

    @app.get("/campaigns/{campaign_id}", response_model=CampaignView)
    def get_campaign(
        campaign_id: str,
        campaign_repository: Annotated[CampaignRepository, Depends(get_repository)],
    ) -> CampaignView:
        return _view(campaign_id, campaign_repository)

    @app.post("/campaigns/{campaign_id}/spec/start", response_model=CampaignView)
    def start_specification(
        campaign_id: str,
        campaign_service: Annotated[CampaignService, Depends(get_service)],
        campaign_repository: Annotated[CampaignRepository, Depends(get_repository)],
        actor: Actor = "human:user",
    ) -> CampaignView:
        campaign_service.start_specification(campaign_id, actor)
        return _view(campaign_id, campaign_repository)

    @app.put("/campaigns/{campaign_id}/spec", response_model=CampaignView)
    def put_design_spec(
        campaign_id: str,
        design_spec: DesignSpec,
        campaign_service: Annotated[CampaignService, Depends(get_service)],
        campaign_repository: Annotated[CampaignRepository, Depends(get_repository)],
    ) -> CampaignView:
        campaign_service.put_design_spec(campaign_id, design_spec)
        return _view(campaign_id, campaign_repository)

    @app.post("/campaigns/{campaign_id}/spec/submit", response_model=CampaignView)
    def submit_design_spec(
        campaign_id: str,
        campaign_service: Annotated[CampaignService, Depends(get_service)],
        campaign_repository: Annotated[CampaignRepository, Depends(get_repository)],
        actor: Actor = "human:user",
    ) -> CampaignView:
        campaign_service.submit_design_spec(campaign_id, actor)
        return _view(campaign_id, campaign_repository)

    @app.post("/campaigns/{campaign_id}/spec/approve", response_model=CampaignView)
    def approve_design_spec(
        campaign_id: str,
        campaign_service: Annotated[CampaignService, Depends(get_service)],
        campaign_repository: Annotated[CampaignRepository, Depends(get_repository)],
        actor: Actor = "human:user",
    ) -> CampaignView:
        campaign_service.approve_design_spec(campaign_id, actor)
        return _view(campaign_id, campaign_repository)

    return app


def _view(campaign_id: str, repository: CampaignRepository) -> CampaignView:
    campaign, design_spec, state_transitions = repository.get_campaign_view(campaign_id)
    return CampaignView(
        campaign=campaign,
        design_spec=design_spec,
        state_transitions=state_transitions,
    )
