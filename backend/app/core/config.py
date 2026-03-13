from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # App
    app_env: str = "development"
    secret_key: str = "dev-secret-key"
    frontend_url: str = "http://localhost:5173"

    # Database
    database_url: str = "postgresql+asyncpg://postgres:password@localhost:5432/backend"
    sf_database_url: str = ""  # existing DB (read-only)

    # Redis
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"

    # Microsoft Graph
    azure_tenant_id: str = ""
    azure_client_id: str = ""
    azure_client_secret: str = ""
    outlook_mailbox: str = "agent@support.ch"
    graph_webhook_secret: str = "dev-webhook-secret"
    webhook_base_url: str = "https://your-ngrok-id.ngrok.io"

    # AI
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"

    # Integrations
    sentry_dsn: str = ""
    posthog_api_key: str = ""
    posthog_host: str = "https://app.posthog.com"

    @property
    def graph_webhook_url(self) -> str:
        return f"{self.webhook_base_url}/api/v1/webhook/graph"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
