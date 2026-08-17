from __future__ import annotations

import tomllib
from pathlib import Path

from proto_virtual_lab.proto_revisions import (
    PROTO_LANGUAGE_COMMIT,
    PROTO_TOOLS_COMMIT,
    require_pinned_proto,
)


def test_declared_proto_dependencies_use_exact_verified_commits() -> None:
    project_root = Path(__file__).resolve().parents[1]
    configuration = tomllib.loads((project_root / "pyproject.toml").read_text(encoding="utf-8"))
    dependencies = configuration["project"]["dependencies"]
    overrides = configuration["tool"]["uv"]["override-dependencies"]

    assert any(
        f"proto-language @ git+https://github.com/evo-design/proto-language.git@{PROTO_LANGUAGE_COMMIT}" == item
        for item in dependencies
    )
    assert overrides == [f"proto-tools @ git+https://github.com/evo-design/proto-tools.git@{PROTO_TOOLS_COMMIT}"]

    manifest = require_pinned_proto()
    assert manifest.revisions_verified is True
    assert manifest.proto_language_commit == PROTO_LANGUAGE_COMMIT
    assert manifest.proto_tools_commit == PROTO_TOOLS_COMMIT
    assert len(manifest.lock_sha256) == 64
    assert manifest.lock_source == "workspace:uv.lock"
    assert manifest.lock_verified is True
