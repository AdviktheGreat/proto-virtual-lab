"""Shared helpers for deterministic artifact persistence and hashing."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from uuid import uuid4


def write_json(path: Path, value: object) -> None:
    """Atomically write consistently formatted JSON."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(f"{path.suffix}.{uuid4().hex}.tmp")
    temporary_path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary_path.replace(path)


def sha256_file(path: Path) -> str:
    """Hash a file without loading it entirely into memory."""

    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


__all__ = ["sha256_file", "write_json"]
