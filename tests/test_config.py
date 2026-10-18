from sql_agent.config import Settings


def test_defaults_point_at_the_local_olist_database(monkeypatch):
    # Defaults only: environment variables would override them.
    for var in ("DATABASE_URL", "ADMIN_DATABASE_URL"):
        monkeypatch.delenv(var, raising=False)
    settings = Settings(_env_file=None)
    assert "127.0.0.1:5433/olist" in settings.database_url.get_secret_value()
    assert settings.database_url.get_secret_value().startswith("postgresql://agent_ro:")
