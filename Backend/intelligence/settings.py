from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class IntelligenceSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="INTELLIGENCE_", env_file=".env", extra="ignore")

    #: Must be supplied per deployment as INTELLIGENCE_SERVICE_TOKEN. There is
    #: deliberately no default: a constant checked into the repository is a
    #: published credential, and an empty one would make compare_digest below
    #: succeed against a request that sent no token at all.
    service_token: str = ""
    service_name: str = "caresense-intelligence"
    require_correlation_id: bool = True

    # When no trained model artifact is registered, inference returns a safe
    # REVIEW_REQUIRED verdict rather than a fabricated score.
    models_dir: str = "intelligence/_artifacts"

    otel_enabled: bool = False


@lru_cache
def get_settings() -> IntelligenceSettings:
    return IntelligenceSettings()
