"""SQLite persistence and content snapshots for campaign contracts."""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from proto_virtual_lab.models import Campaign, DesignSpec, StateTransition


class RecordNotFoundError(LookupError):
    """Raised when a requested persisted record does not exist."""


class DuplicateRecordError(ValueError):
    """Raised when a record identifier already exists."""


class ConcurrentUpdateError(RuntimeError):
    """Raised when persisted campaign state changed after it was read."""


class CampaignRepository:
    """Persist campaign state and audit transitions atomically in SQLite."""

    def __init__(self, database_path: Path, artifact_root: Path) -> None:
        self.database_path = database_path
        self.artifact_root = artifact_root
        self._write_lock = threading.Lock()

    def initialize(self) -> None:
        """Create storage directories and the Milestone 1 database schema."""

        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.artifact_root.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS campaigns (
                    id TEXT PRIMARY KEY,
                    version INTEGER NOT NULL,
                    created_at TEXT,
                    data TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS design_specs (
                    id TEXT PRIMARY KEY,
                    campaign_id TEXT NOT NULL UNIQUE,
                    data TEXT NOT NULL,
                    FOREIGN KEY (campaign_id) REFERENCES campaigns(id)
                );
                CREATE TABLE IF NOT EXISTS design_spec_revisions (
                    id TEXT PRIMARY KEY,
                    campaign_id TEXT NOT NULL,
                    data TEXT NOT NULL,
                    FOREIGN KEY (campaign_id) REFERENCES campaigns(id)
                );
                CREATE TABLE IF NOT EXISTS state_transitions (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    id TEXT NOT NULL UNIQUE,
                    campaign_id TEXT NOT NULL,
                    data TEXT NOT NULL,
                    FOREIGN KEY (campaign_id) REFERENCES campaigns(id)
                );
                CREATE INDEX IF NOT EXISTS idx_state_transitions_campaign
                    ON state_transitions(campaign_id, sequence);
                """
            )
            campaign_columns = {row["name"] for row in connection.execute("PRAGMA table_info(campaigns)").fetchall()}
            if "created_at" not in campaign_columns:
                connection.execute("ALTER TABLE campaigns ADD COLUMN created_at TEXT")
            connection.execute(
                "UPDATE campaigns SET created_at = json_extract(data, '$.created_at') WHERE created_at IS NULL"
            )
            connection.execute("CREATE INDEX IF NOT EXISTS idx_campaigns_created_at ON campaigns(created_at DESC)")
            connection.execute(
                """
                INSERT OR IGNORE INTO design_spec_revisions (id, campaign_id, data)
                SELECT id, campaign_id, data FROM design_specs
                """
            )

    def create_campaign(
        self,
        campaign: Campaign,
        transition: StateTransition,
        design_spec: DesignSpec | None = None,
    ) -> None:
        """Insert a campaign, initial event, and optional carried spec atomically."""

        with self._write_lock:
            try:
                with self._connection() as connection:
                    connection.execute(
                        "INSERT INTO campaigns (id, version, created_at, data) VALUES (?, ?, ?, ?)",
                        (
                            campaign.id,
                            campaign.version,
                            campaign.created_at.isoformat(),
                            self._dump(campaign),
                        ),
                    )
                    if design_spec is not None:
                        self._upsert_design_spec(connection, design_spec)
                    self._insert_transition(connection, transition)
                    self._write_campaign_snapshot(campaign)
                    if design_spec is not None:
                        self._write_design_spec_snapshots(design_spec)
                    self._write_transition_snapshot(transition)
            except sqlite3.IntegrityError as error:
                raise DuplicateRecordError(f"campaign {campaign.id} already exists") from error

    def get_campaign(self, campaign_id: str) -> Campaign:
        with self._connection() as connection:
            row = connection.execute("SELECT data FROM campaigns WHERE id = ?", (campaign_id,)).fetchone()
        if row is None:
            raise RecordNotFoundError(f"campaign {campaign_id} was not found")
        return Campaign.model_validate_json(row["data"])

    def list_campaigns(self, limit: int = 50, offset: int = 0) -> list[Campaign]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT data FROM campaigns ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        return [Campaign.model_validate_json(row["data"]) for row in rows]

    def get_campaign_view(self, campaign_id: str) -> tuple[Campaign, DesignSpec | None, list[StateTransition]]:
        """Load a complete campaign view using one consistent database snapshot."""

        with self._connection() as connection:
            campaign_row = connection.execute("SELECT data FROM campaigns WHERE id = ?", (campaign_id,)).fetchone()
            if campaign_row is None:
                raise RecordNotFoundError(f"campaign {campaign_id} was not found")
            design_spec_row = connection.execute(
                "SELECT data FROM design_specs WHERE campaign_id = ?", (campaign_id,)
            ).fetchone()
            transition_rows = connection.execute(
                "SELECT data FROM state_transitions WHERE campaign_id = ? ORDER BY sequence",
                (campaign_id,),
            ).fetchall()
        return (
            Campaign.model_validate_json(campaign_row["data"]),
            None if design_spec_row is None else DesignSpec.model_validate_json(design_spec_row["data"]),
            [StateTransition.model_validate_json(row["data"]) for row in transition_rows],
        )

    def get_design_spec(self, campaign_id: str) -> DesignSpec | None:
        with self._connection() as connection:
            row = connection.execute("SELECT data FROM design_specs WHERE campaign_id = ?", (campaign_id,)).fetchone()
        return None if row is None else DesignSpec.model_validate_json(row["data"])

    def get_transitions(self, campaign_id: str) -> list[StateTransition]:
        with self._connection() as connection:
            exists = connection.execute("SELECT 1 FROM campaigns WHERE id = ?", (campaign_id,)).fetchone()
            if exists is None:
                raise RecordNotFoundError(f"campaign {campaign_id} was not found")
            rows = connection.execute(
                "SELECT data FROM state_transitions WHERE campaign_id = ? ORDER BY sequence",
                (campaign_id,),
            ).fetchall()
        return [StateTransition.model_validate_json(row["data"]) for row in rows]

    def commit_update(
        self,
        campaign: Campaign,
        transition: StateTransition | None = None,
        design_spec: DesignSpec | None = None,
        expected_campaign: Campaign | None = None,
    ) -> None:
        """Atomically update a campaign with an optional spec and transition."""

        with self._write_lock:
            try:
                with self._connection() as connection:
                    if expected_campaign is None:
                        cursor = connection.execute(
                            "UPDATE campaigns SET version = ?, data = ? WHERE id = ?",
                            (campaign.version, self._dump(campaign), campaign.id),
                        )
                    else:
                        cursor = connection.execute(
                            "UPDATE campaigns SET version = ?, data = ? WHERE id = ? AND data = ?",
                            (
                                campaign.version,
                                self._dump(campaign),
                                campaign.id,
                                self._dump(expected_campaign),
                            ),
                        )
                    if cursor.rowcount != 1:
                        exists = connection.execute("SELECT 1 FROM campaigns WHERE id = ?", (campaign.id,)).fetchone()
                        if exists is None:
                            raise RecordNotFoundError(f"campaign {campaign.id} was not found")
                        raise ConcurrentUpdateError(
                            f"campaign {campaign.id} changed before this update could be committed"
                        )
                    if design_spec is not None:
                        self._upsert_design_spec(connection, design_spec)
                    if transition is not None:
                        self._insert_transition(connection, transition)
                    self._write_campaign_snapshot(campaign)
                    if design_spec is not None:
                        self._write_design_spec_snapshots(design_spec)
                    if transition is not None:
                        self._write_transition_snapshot(transition)
            except sqlite3.IntegrityError as error:
                raise DuplicateRecordError(
                    "a persisted artifact identifier conflicts with an existing record"
                ) from error

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    @staticmethod
    def _insert_transition(connection: sqlite3.Connection, transition: StateTransition) -> None:
        connection.execute(
            "INSERT INTO state_transitions (id, campaign_id, data) VALUES (?, ?, ?)",
            (transition.id, transition.campaign_id, CampaignRepository._dump(transition)),
        )

    @staticmethod
    def _upsert_design_spec(connection: sqlite3.Connection, design_spec: DesignSpec) -> None:
        serialized = CampaignRepository._dump(design_spec)
        connection.execute(
            "INSERT INTO design_spec_revisions (id, campaign_id, data) VALUES (?, ?, ?)",
            (design_spec.id, design_spec.campaign_id, serialized),
        )
        connection.execute(
            """
            INSERT INTO design_specs (id, campaign_id, data)
            VALUES (?, ?, ?)
            ON CONFLICT(campaign_id) DO UPDATE SET
                id = excluded.id,
                data = excluded.data
            """,
            (design_spec.id, design_spec.campaign_id, serialized),
        )

    @staticmethod
    def _dump(model: Campaign | DesignSpec | StateTransition) -> str:
        return model.model_dump_json()

    def _write_campaign_snapshot(self, campaign: Campaign) -> None:
        self._write_model_snapshot(campaign.id, "campaign.json", campaign)

    def _write_transition_snapshot(self, transition: StateTransition) -> None:
        self._write_model_snapshot(
            transition.campaign_id,
            f"transitions/{transition.id}.json",
            transition,
        )

    def _write_design_spec_snapshots(self, design_spec: DesignSpec) -> None:
        self._write_model_snapshot(design_spec.campaign_id, "design_spec.json", design_spec)
        self._write_model_snapshot(
            design_spec.campaign_id,
            f"design_specs/{design_spec.id}.json",
            design_spec,
        )

    def _write_model_snapshot(
        self, campaign_id: str, filename: str, model: Campaign | DesignSpec | StateTransition
    ) -> None:
        self._write_json(self._campaign_directory(campaign_id) / filename, model.model_dump(mode="json"))

    def _campaign_directory(self, campaign_id: str) -> Path:
        directory = self.artifact_root / "campaigns" / campaign_id
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    @staticmethod
    def _write_json(path: Path, value: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = path.with_suffix(f"{path.suffix}.{uuid4().hex}.tmp")
        temporary_path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary_path.replace(path)
