from app.config.settings import Settings


def test_env_file_secrets_are_loaded_and_redacted(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    env = tmp_path / ".env"
    env.write_text(
        "OPENAI_API_KEY=test-only-openai\nGITHUB_TOKEN=test-only-github\n", encoding="utf-8"
    )
    settings = Settings(_env_file=env)
    assert settings.openai_api_key.get_secret_value() == "test-only-openai"
    assert settings.github_token.get_secret_value() == "test-only-github"
    assert "test-only" not in repr(settings)
