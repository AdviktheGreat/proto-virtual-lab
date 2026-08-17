from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from pydantic import ValidationError

from proto_virtual_lab.models import ProtoSmokeRequest, ProtoSmokeRun, ProtoSmokeStatus
from proto_virtual_lab.proto_smoke import (
    ProtoSmokeBusyError,
    ProtoSmokeExecutionError,
    ProtoSmokeRunner,
    ProtoSmokeRunNotFoundError,
)


def test_authentic_smoke_run_exports_hashes_and_replays(tmp_path: Path) -> None:
    runner = ProtoSmokeRunner(tmp_path)

    result = runner.run(ProtoSmokeRequest())

    assert result.status is ProtoSmokeStatus.SUCCEEDED
    assert len(result.sequences) == 2
    assert all(len(sequence) == 24 for sequence in result.sequences)
    assert all(set(sequence) <= set("ACGT") for sequence in result.sequences)
    assert result.energy_scores == [0.0, 0.0]
    assert result.export_files == [
        "constraints.json",
        "constructs.json",
        "optimization.json",
        "sequences.fasta",
        "sequences.json",
    ]
    assert result.manifest.revisions_verified is True

    export_directory = tmp_path / result.output_directory
    for relative_path, expected_hash in result.export_sha256.items():
        content = (export_directory / relative_path).read_bytes()
        assert hashlib.sha256(content).hexdigest() == expected_hash

    assert runner.get(result.id) == result
    repeated = runner.run(result.request)
    assert repeated.sequences == result.sequences
    assert repeated.energy_scores == result.energy_scores
    assert repeated.export_sha256 == result.export_sha256

    legacy_run = result.model_dump(mode="json")
    del legacy_run["manifest"]["lock_source"]
    del legacy_run["manifest"]["lock_verified"]
    loaded_legacy_run = ProtoSmokeRun.model_validate(legacy_run)
    assert loaded_legacy_run.manifest.lock_source == "legacy:unrecorded"
    assert loaded_legacy_run.manifest.lock_verified is False

    invalid_timestamps = result.model_dump()
    invalid_timestamps["completed_at"] = result.started_at.replace(year=result.started_at.year - 1)
    with pytest.raises(ValidationError, match="cannot precede"):
        ProtoSmokeRun.model_validate(invalid_timestamps)

    invalid_sequences = result.model_dump()
    invalid_sequences["sequences"] = result.sequences[:1]
    with pytest.raises(ValidationError, match="sequence count"):
        ProtoSmokeRun.model_validate(invalid_sequences)

    invalid_scores = result.model_dump()
    invalid_scores["energy_scores"] = result.energy_scores[:1]
    with pytest.raises(ValidationError, match="energy score count"):
        ProtoSmokeRun.model_validate(invalid_scores)

    invalid_lengths = result.model_dump()
    invalid_lengths["sequences"] = [sequence[:-1] for sequence in result.sequences]
    with pytest.raises(ValidationError, match="sequence lengths"):
        ProtoSmokeRun.model_validate(invalid_lengths)

    invalid_exports = result.model_dump()
    invalid_exports["export_files"] = result.export_files[:-1]
    with pytest.raises(ValidationError, match="same artifacts"):
        ProtoSmokeRun.model_validate(invalid_exports)


def test_smoke_request_enforces_bounded_work() -> None:
    with pytest.raises(ValidationError, match="less than or equal to 32"):
        ProtoSmokeRequest(num_samples=100)

    with pytest.raises(ValidationError, match="cannot exceed"):
        ProtoSmokeRequest(num_samples=2, num_results=3)


def test_smoke_timeout_is_reported(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def time_out(*args: object, **kwargs: object) -> int:
        raise ProtoSmokeExecutionError("Proto smoke run exceeded its 10-second timeout")

    monkeypatch.setattr(ProtoSmokeRunner, "_execute_worker", staticmethod(time_out))

    with pytest.raises(ProtoSmokeExecutionError, match="exceeded its 10-second timeout"):
        ProtoSmokeRunner(tmp_path).run(ProtoSmokeRequest(timeout_seconds=10))
    assert not list((tmp_path / "proto-smoke").iterdir())


def test_smoke_capacity_is_bounded(tmp_path: Path) -> None:
    runner = ProtoSmokeRunner(tmp_path)
    assert runner._capacity.acquire(blocking=False)
    assert runner._capacity.acquire(blocking=False)
    try:
        with pytest.raises(ProtoSmokeBusyError, match="capacity"):
            runner.run(ProtoSmokeRequest())
    finally:
        runner._capacity.release()
        runner._capacity.release()


def test_malformed_worker_artifacts_are_reported(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        ProtoSmokeRunner,
        "_execute_worker",
        staticmethod(lambda *args, **kwargs: 0),
    )

    with pytest.raises(ProtoSmokeExecutionError, match="invalid artifacts"):
        ProtoSmokeRunner(tmp_path).run(ProtoSmokeRequest())
    assert not list((tmp_path / "proto-smoke").iterdir())


def test_relative_artifact_root_is_resolved_before_worker_launch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    runner = ProtoSmokeRunner(Path("relative-artifacts"))

    result = runner.run(ProtoSmokeRequest(num_samples=2, num_results=1))

    assert (tmp_path / "relative-artifacts" / result.output_directory).is_dir()


def test_invalid_or_missing_smoke_run_is_not_found(tmp_path: Path) -> None:
    runner = ProtoSmokeRunner(tmp_path)

    with pytest.raises(ProtoSmokeRunNotFoundError):
        runner.get("../../outside")
    with pytest.raises(ProtoSmokeRunNotFoundError):
        runner.get("proto_smoke_missing")
