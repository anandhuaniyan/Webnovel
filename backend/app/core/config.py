from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    app_name: str = "Webnovel"
    environment: str = Field(default="development", validation_alias="WEBNOVEL_ENVIRONMENT")
    api_prefix: str = "/api"

    project_root: Path = Field(validation_alias="WEBNOVEL_PROJECT_ROOT")
    data_path: Path = Field(validation_alias="WEBNOVEL_DATA_PATH")
    storage_path: Path = Field(validation_alias="WEBNOVEL_STORAGE_PATH")
    logs_path: Path = Field(validation_alias="WEBNOVEL_LOGS_PATH")
    backups_path: Path = Field(validation_alias="WEBNOVEL_BACKUPS_PATH")

    database_url: str = Field(validation_alias="WEBNOVEL_DATABASE_URL")
    expected_database_name: str = "webnovel"
    redis_url: str = Field(validation_alias="WEBNOVEL_REDIS_URL")

    public_base_url: str = Field(default="http://localhost:5273", validation_alias="WEBNOVEL_FRONTEND_URL")
    backend_url: str = Field(default="http://localhost:8270", validation_alias="WEBNOVEL_BACKEND_URL")
    jwt_secret: str = Field(default="change-me", validation_alias="WEBNOVEL_JWT_SECRET")
    jwt_expire_minutes: int = 60 * 24 * 14
    admin_api_key: str = Field(default="change-me", validation_alias="WEBNOVEL_ADMIN_API_KEY")

    adsense_enabled: bool = Field(default=False, validation_alias="ADSENSE_ENABLED")
    adsense_auto_ads: bool = Field(default=False, validation_alias="ADSENSE_AUTO_ADS")
    adsense_client_id: str = Field(default="", validation_alias="NEXT_PUBLIC_ADSENSE_CLIENT_ID")
    adsense_publisher_id: str = Field(default="", validation_alias="ADSENSE_PUBLISHER_ID")
    ga_measurement_id: str = Field(default="", validation_alias="NEXT_PUBLIC_GA_MEASUREMENT_ID")
    consent_provider: str = Field(default="local", validation_alias="WEBNOVEL_CONSENT_PROVIDER")

    ai_image_provider: str = Field(default="disabled", validation_alias="WEBNOVEL_AI_IMAGE_PROVIDER")
    ai_image_endpoint: str = Field(default="", validation_alias="WEBNOVEL_AI_IMAGE_ENDPOINT")
    ai_image_api_key: str = Field(default="", validation_alias="WEBNOVEL_AI_IMAGE_API_KEY")
    ai_metadata_provider: str = Field(default="disabled", validation_alias="WEBNOVEL_AI_METADATA_PROVIDER")
    rights_jurisdiction: str = Field(default="SG", validation_alias="WEBNOVEL_RIGHTS_JURISDICTION")
    rights_rules_path: Path = Field(
        default=Path("/app/app/config/rights_rules.json"),
        validation_alias="WEBNOVEL_RIGHTS_RULES_PATH",
    )

    storage_warning_threshold: int = 70
    storage_critical_threshold: int = 80
    storage_emergency_threshold: int = 90

    @field_validator("database_url")
    @classmethod
    def validate_database_identity(cls, value: str) -> str:
        parsed = urlparse(value.replace("postgresql+psycopg", "postgresql", 1))
        database_name = parsed.path.lstrip("/").split("?", 1)[0]
        if database_name != "webnovel":
            raise ValueError(f"database must be 'webnovel', got '{database_name or '<missing>'}'")
        if value.startswith("postgresql://"):
            return value.replace("postgresql://", "postgresql+psycopg://", 1)
        return value

    @model_validator(mode="after")
    def validate_isolated_paths(self) -> Settings:
        root = self.project_root.resolve()
        for name in ("data_path", "storage_path", "logs_path", "backups_path"):
            path = getattr(self, name).resolve()
            if path != root and root not in path.parents:
                raise ValueError(f"{name} points outside the Webnovel project root: {path}")
        if self.environment == "production" and self.jwt_secret == "change-me":
            raise ValueError("WEBNOVEL_JWT_SECRET must be configured in production")
        if self.ai_image_provider == "http":
            endpoint = urlparse(self.ai_image_endpoint)
            if endpoint.scheme not in {"http", "https"} or not endpoint.netloc:
                raise ValueError("WEBNOVEL_AI_IMAGE_ENDPOINT must be an absolute HTTP(S) URL")
            if not self.ai_image_api_key:
                raise ValueError("WEBNOVEL_AI_IMAGE_API_KEY is required for the HTTP image provider")
            if self.environment == "production" and endpoint.scheme != "https":
                raise ValueError("WEBNOVEL_AI_IMAGE_ENDPOINT must use HTTPS in production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
