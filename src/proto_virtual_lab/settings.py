"""Application configuration with environment-variable overrides."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings for the API and persistence layer."""

    model_config = SettingsConfigDict(env_prefix="PROTO_VIRTUAL_LAB_", extra="ignore")

    database_path: Path = Path("data/proto_virtual_lab.sqlite3")
    artifact_root: Path = Path("artifacts")
