"""Settings read from the environment and `.env`. Secrets live only there."""

from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # The owner role: creates the schema, loads the CSVs, manages agent_ro.
    admin_database_url: SecretStr = SecretStr(
        "postgresql://olist_admin:olist-dev@127.0.0.1:5433/olist"
    )
    # Password the loader gives agent_ro, the read-only role the agent runs as.
    agent_ro_password: SecretStr = SecretStr("agent-ro-dev")
    # Connection the agent uses: agent_ro, SELECT only on schema olist, 5 s timeout.
    database_url: SecretStr = SecretStr("postgresql://agent_ro:agent-ro-dev@127.0.0.1:5433/olist")


@lru_cache
def get_settings() -> Settings:
    return Settings()
