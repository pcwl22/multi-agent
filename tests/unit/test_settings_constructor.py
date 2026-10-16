from pydantic import SecretStr

from app.config.settings import Settings


def test_programmatic_credentials_are_not_ignored_by_environment_aliases(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    settings = Settings(
        _env_file=None,
        openai_api_key=SecretStr("unit-provider-secret"),
        github_token=SecretStr("unit-github-secret"),
    )
    assert settings.openai_api_key.get_secret_value() == "unit-provider-secret"
    assert settings.github_token.get_secret_value() == "unit-github-secret"
    assert "unit-provider-secret" not in repr(settings)
    assert "unit-github-secret" not in repr(settings)
