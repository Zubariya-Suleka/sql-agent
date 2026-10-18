"""Settings read from the environment and `.env`. Secrets live only there."""

from functools import lru_cache
from pathlib import Path

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

    # llm-gateway (port 8100: issue-radar's own gateway already uses 8000 on this machine).
    gateway_url: str = "http://127.0.0.1:8100/v1"
    agent_model: str = "groq/openai/gpt-oss-20b"
    # Generous: the gateway may hold a request while it waits for rate-limit budget.
    gateway_timeout_s: float = 300.0
    # Reasoning models spend output tokens thinking before the tool call itself.
    max_completion_tokens: int = 2048
    max_steps: int = 8
    runs_dir: Path = Path("runs")


@lru_cache
def get_settings() -> Settings:
    return Settings()
