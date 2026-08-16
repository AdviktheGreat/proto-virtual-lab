from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from proto_virtual_lab.api import create_app
from proto_virtual_lab.service import CampaignService
from proto_virtual_lab.settings import Settings
from proto_virtual_lab.storage import CampaignRepository


@pytest.fixture
def repository(tmp_path: Path) -> CampaignRepository:
    value = CampaignRepository(tmp_path / "test.sqlite3", tmp_path / "artifacts")
    value.initialize()
    return value


@pytest.fixture
def service(repository: CampaignRepository) -> CampaignService:
    return CampaignService(repository)


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    app = create_app(
        Settings(
            database_path=tmp_path / "api.sqlite3",
            artifact_root=tmp_path / "api-artifacts",
        )
    )
    with TestClient(app) as value:
        yield value
