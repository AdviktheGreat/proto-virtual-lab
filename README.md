# Proto Virtual Lab

Proto Virtual Lab is a typed, auditable scientific decision and control layer for
[Proto](https://proto.evodesign.org/). It turns a biological design objective into a reviewable
specification, evidence-backed plan, validated Proto program, and computational candidate dossier.

The system treats every output as a computational hypothesis. It does not claim experimental
validation or replace wet-lab evaluation.

## Milestone 1

The current milestone provides:

- Strict Pydantic contracts for campaign, evidence, planning, critique, execution, and dossier artifacts.
- A deterministic 20-state campaign lifecycle with explicit approval and revision gates.
- SQLite persistence with JSON artifact snapshots and an append-only transition audit trail.
- A seeded synthetic promoter-repressor `DesignSpec`.
- A FastAPI surface for campaign creation, specification submission, approval, reload, and replay.

LLM agents, Paperclip, live Proto discovery, compilation, and scientific execution are intentionally
deferred to later milestones.

## Requirements

- Python 3.12
- [`uv`](https://docs.astral.sh/uv/)

## Set up

```bash
uv sync --extra dev
```

## Run the API

```bash
uv run proto-virtual-lab
```

The API listens on `http://127.0.0.1:8000`. Interactive documentation is available at `/docs`.

Create a seeded campaign:

```bash
curl -X POST http://127.0.0.1:8000/campaigns/seeded \
  -H 'X-Actor: human:scientist'
```

The campaign stops at `SPEC_AWAITING_APPROVAL`. Approve it explicitly:

```bash
curl -X POST http://127.0.0.1:8000/campaigns/CAMPAIGN_ID/spec/approve \
  -H 'X-Actor: human:reviewer'
```

## Validate

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run pytest --cov
```

## Persistence

Defaults:

- SQLite: `data/proto_virtual_lab.sqlite3`
- Artifact snapshots: `artifacts/campaigns/<campaign-id>/`

Each state transition and `DesignSpec` revision is stored under its own identifier. `campaign.json`
and `design_spec.json` are current-state pointers; immutable history remains under `transitions/`
and `design_specs/`.

Override them with:

```bash
export PROTO_VIRTUAL_LAB_DATABASE_PATH=/durable/path/proto_virtual_lab.sqlite3
export PROTO_VIRTUAL_LAB_ARTIFACT_ROOT=/durable/path/artifacts
```

SQLite is the Milestone 1 persistence implementation. The application layer keeps storage behind a
repository boundary so a hosted database can replace it without changing workflow contracts.
Campaign listing is paginated with `limit` (maximum 100) and `offset` query parameters.

## Scientific scope

The seeded campaign is a benign synthetic promoter-repressor design exercise. Its required claim ceiling is:

> Computationally nominated; experimental validation required.

Heavyweight execution remains blocked until the original model, software, licensing, and compute access
requirements are satisfied.
