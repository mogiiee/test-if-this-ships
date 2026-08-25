from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    port: int = 8787
    anthropic_api_key: str = ""
    model_triage: str = "claude-haiku-4-5"
    model_sonnet: str = "claude-sonnet-5"
    model_opus: str = "claude-opus-5"
    github_app_id: str = ""
    github_app_private_key: str = ""
    github_webhook_secret: str = ""
    github_token: str = ""
    core_repo: str = "QdRepo/appt_bridge_core"
    bot_login: str = "groundskeeper"

    def normalized_private_key(self) -> str:
        return self.github_app_private_key.replace("\\n", "\n")

    def has_github_app(self) -> bool:
        return bool(
            self.github_app_id
            and self.github_app_private_key
            and self.github_webhook_secret
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
