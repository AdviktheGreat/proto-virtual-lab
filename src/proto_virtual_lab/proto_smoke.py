"""Isolated execution service for the bounded authentic Proto smoke campaign."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from pydantic import TypeAdapter, ValidationError

from proto_virtual_lab.artifacts import sha256_file, write_json
from proto_virtual_lab.models import (
    ArtifactId,
    ProtoSmokeRequest,
    ProtoSmokeRun,
    ProtoSmokeStatus,
    ProtoSmokeWorkerResult,
)
from proto_virtual_lab.proto_revisions import require_pinned_proto

_ARTIFACT_ID_ADAPTER = TypeAdapter(ArtifactId)
_MAX_CAPTURE_BYTES = 20_000
_MAX_CONCURRENT_RUNS = 2


class ProtoSmokeExecutionError(RuntimeError):
    """Raised when the isolated Proto smoke worker fails or times out."""


class ProtoSmokeBusyError(RuntimeError):
    """Raised when the bounded local smoke execution capacity is occupied."""


class ProtoSmokeRunNotFoundError(LookupError):
    """Raised when a requested smoke run artifact does not exist."""


class ProtoSmokeRunner:
    """Run the fixed smoke program in a subprocess with bounded inputs and outputs."""

    def __init__(self, artifact_root: Path) -> None:
        self.artifact_root = artifact_root.resolve()
        self._capacity = threading.BoundedSemaphore(_MAX_CONCURRENT_RUNS)

    def run(self, request: ProtoSmokeRequest) -> ProtoSmokeRun:
        """Execute and persist one authentic, reproducible Proto smoke run."""

        if not self._capacity.acquire(blocking=False):
            raise ProtoSmokeBusyError("Proto smoke execution capacity is currently full")
        try:
            return self._run(request)
        finally:
            self._capacity.release()

    def _run(self, request: ProtoSmokeRequest) -> ProtoSmokeRun:
        manifest = require_pinned_proto()
        run_id = f"proto_smoke_{uuid4().hex}"
        run_directory = self.artifact_root / "proto-smoke" / run_id
        export_directory = run_directory / "export"
        request_path = run_directory / "request.json"
        result_path = run_directory / "worker_result.json"
        source_path = Path(__file__).with_name("proto_smoke_worker.py")
        run_directory.mkdir(parents=True, exist_ok=False)
        try:
            write_json(request_path, request.model_dump(mode="json"))
            source_snapshot = run_directory / "source_snapshot.py"
            shutil.copyfile(source_path, source_snapshot)
            stdout_path = run_directory / "stdout.log"
            stderr_path = run_directory / "stderr.log"
            started_at = datetime.now(UTC)
            command = [
                sys.executable,
                "-m",
                "proto_virtual_lab.proto_smoke_worker",
                "--request",
                str(request_path),
                "--output-directory",
                str(export_directory),
                "--result",
                str(result_path),
            ]
            return_code = self._execute_worker(
                command,
                run_directory,
                self._worker_environment(run_directory),
                request.timeout_seconds,
                stdout_path,
                stderr_path,
            )
            completed_at = datetime.now(UTC)
            stdout = self._read_tail(stdout_path)
            stderr = self._read_tail(stderr_path)
            if return_code != 0:
                raise ProtoSmokeExecutionError(
                    f"Proto smoke worker failed with exit code {return_code}: {self._last_line(stderr or stdout)}"
                )

            worker_result = ProtoSmokeWorkerResult.model_validate_json(result_path.read_text(encoding="utf-8"))
            export_hashes = self._hash_exports(export_directory)
            smoke_run = ProtoSmokeRun(
                id=run_id,
                status=ProtoSmokeStatus.SUCCEEDED,
                started_at=started_at,
                completed_at=completed_at,
                request=request,
                manifest=manifest,
                source_sha256=sha256_file(source_snapshot),
                output_directory=str(export_directory.relative_to(self.artifact_root)),
                sequences=worker_result.sequences,
                energy_scores=worker_result.energy_scores,
                export_files=sorted(export_hashes),
                export_sha256=export_hashes,
                stdout=stdout,
                stderr=stderr,
            )
            write_json(run_directory / "run.json", smoke_run.model_dump(mode="json"))
            return smoke_run
        except ProtoSmokeExecutionError:
            shutil.rmtree(run_directory, ignore_errors=True)
            raise
        except (OSError, ValidationError) as error:
            shutil.rmtree(run_directory, ignore_errors=True)
            raise ProtoSmokeExecutionError(f"Proto smoke worker produced invalid artifacts: {error}") from error

    def get(self, run_id: str) -> ProtoSmokeRun:
        """Reload a completed smoke run from its persisted typed artifact."""

        try:
            validated_id = _ARTIFACT_ID_ADAPTER.validate_python(run_id)
        except ValidationError as error:
            raise ProtoSmokeRunNotFoundError(f"Proto smoke run {run_id!r} was not found") from error
        run_path = self.artifact_root / "proto-smoke" / validated_id / "run.json"
        try:
            return ProtoSmokeRun.model_validate_json(run_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise ProtoSmokeRunNotFoundError(f"Proto smoke run {run_id!r} was not found") from None

    @staticmethod
    def _execute_worker(
        command: list[str],
        run_directory: Path,
        environment: dict[str, str],
        timeout_seconds: int,
        stdout_path: Path,
        stderr_path: Path,
    ) -> int:
        with stdout_path.open("wb") as stdout_file, stderr_path.open("wb") as stderr_file:
            process = subprocess.Popen(
                command,
                cwd=run_directory,
                env=environment,
                stdout=stdout_file,
                stderr=stderr_file,
            )
            try:
                return process.wait(timeout=timeout_seconds)
            except subprocess.TimeoutExpired as error:
                process.kill()
                process.wait()
                raise ProtoSmokeExecutionError(
                    f"Proto smoke run exceeded its {timeout_seconds}-second timeout"
                ) from error

    @staticmethod
    def _worker_environment(run_directory: Path) -> dict[str, str]:
        environment = {
            "HOME": os.environ.get("HOME", str(run_directory)),
            "PATH": os.environ.get("PATH", ""),
            "PROTO_HOME": str(run_directory / "proto_home"),
            "PYTHONHASHSEED": "0",
        }
        for optional_name in ("DYLD_LIBRARY_PATH", "LD_LIBRARY_PATH", "TMPDIR"):
            value = os.environ.get(optional_name)
            if value is not None:
                environment[optional_name] = value
        return environment

    @staticmethod
    def _hash_exports(export_directory: Path) -> dict[str, str]:
        if not export_directory.is_dir():
            raise ProtoSmokeExecutionError("Proto smoke worker did not create its export directory")
        return {
            str(path.relative_to(export_directory)): sha256_file(path)
            for path in sorted(export_directory.rglob("*"))
            if path.is_file()
        }

    @staticmethod
    def _read_tail(path: Path) -> str:
        with path.open("rb") as file:
            file.seek(0, os.SEEK_END)
            file.seek(max(0, file.tell() - _MAX_CAPTURE_BYTES))
            return file.read().decode("utf-8", errors="replace")

    @staticmethod
    def _last_line(value: str) -> str:
        lines = value.strip().splitlines()
        return lines[-1] if lines else "no diagnostic output"


__all__ = [
    "ProtoSmokeBusyError",
    "ProtoSmokeExecutionError",
    "ProtoSmokeRunNotFoundError",
    "ProtoSmokeRunner",
]
