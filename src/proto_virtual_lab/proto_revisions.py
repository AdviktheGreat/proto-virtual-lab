"""Pinned Proto revisions and installed-distribution verification."""

from __future__ import annotations

import json
import platform
from datetime import UTC, datetime
from functools import cache
from importlib.metadata import PackageNotFoundError, distribution, version
from importlib.resources import files
from pathlib import Path

from proto_virtual_lab.artifacts import sha256_file
from proto_virtual_lab.models import ReproducibilityManifest

PROTO_LANGUAGE_COMMIT = "edf64afbcf84cc7c5e4e1404418c8ef1f16c34ce"
PROTO_TOOLS_COMMIT = "1e0bd8f5a8f4525eb5e5c736cbf25c1366929e73"


class ProtoRevisionMismatchError(RuntimeError):
    """Raised when an installed Proto package does not match its declared pin."""


def build_reproducibility_manifest() -> ReproducibilityManifest:
    """Describe and verify the installed Proto execution environment."""

    (
        language_version,
        language_commit,
        tools_version,
        tools_commit,
        lock_sha256,
        lock_source,
        lock_verified,
        revisions_verified,
    ) = _environment_fingerprint()
    return ReproducibilityManifest(
        generated_at=datetime.now(UTC),
        python_version=platform.python_version(),
        platform=platform.platform(),
        proto_language_version=language_version,
        proto_language_commit=language_commit or "unknown",
        proto_tools_version=tools_version,
        proto_tools_commit=tools_commit or "unknown",
        lock_sha256=lock_sha256,
        lock_source=lock_source,
        lock_verified=lock_verified,
        revisions_verified=revisions_verified,
        model_revisions={},
        external_tool_versions={},
    )


def require_pinned_proto() -> ReproducibilityManifest:
    """Return the manifest or fail before scientific execution on revision drift."""

    manifest = build_reproducibility_manifest()
    if not manifest.revisions_verified:
        raise ProtoRevisionMismatchError(
            "installed Proto revisions do not match the application pins: "
            f"proto-language={manifest.proto_language_commit}, "
            f"proto-tools={manifest.proto_tools_commit}"
        )
    return manifest


@cache
def _environment_fingerprint() -> tuple[str, str | None, str, str | None, str, str, bool, bool]:
    language_commit = _installed_commit("proto-language")
    tools_commit = _installed_commit("proto-tools")
    lock_sha256, lock_source, lock_verified = _lock_fingerprint()
    revisions_verified = language_commit == PROTO_LANGUAGE_COMMIT and tools_commit == PROTO_TOOLS_COMMIT
    return (
        _installed_version("proto-language"),
        language_commit,
        _installed_version("proto-tools"),
        tools_commit,
        lock_sha256,
        lock_source,
        lock_verified,
        revisions_verified,
    )


def _installed_version(package: str) -> str:
    try:
        return version(package)
    except PackageNotFoundError:
        return "not-installed"


def _installed_commit(package: str) -> str | None:
    try:
        direct_url = distribution(package).read_text("direct_url.json")
    except PackageNotFoundError:
        return None
    if direct_url is None:
        return None
    data = json.loads(direct_url)
    commit_id = data.get("vcs_info", {}).get("commit_id")
    return commit_id if isinstance(commit_id, str) else None


def _lock_fingerprint() -> tuple[str, str, bool]:
    expected_hash = (
        files("proto_virtual_lab").joinpath("reproducibility/uv.lock.sha256").read_text(encoding="utf-8").strip()
    )
    for parent in Path(__file__).resolve().parents:
        lock_path = parent / "uv.lock"
        if lock_path.is_file():
            actual_hash = sha256_file(lock_path)
            return actual_hash, "workspace:uv.lock", actual_hash == expected_hash
    return expected_hash, "packaged-expected-digest", False


__all__ = [
    "PROTO_LANGUAGE_COMMIT",
    "PROTO_TOOLS_COMMIT",
    "ProtoRevisionMismatchError",
    "build_reproducibility_manifest",
    "require_pinned_proto",
]
