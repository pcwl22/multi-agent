from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="REPOPILOT_", env_file=".env", extra="ignore", populate_by_name=True
    )
    repository_root: Path = Path("demo_repository")
    data_dir: Path = Path(".repopilot")
    model_mode: Literal["mock", "live"] = "mock"
    model_name: str = "gpt-4.1-mini"
    model_base_url: str | None = None
    openai_api_key: SecretStr | None = Field(default=None, validation_alias="OPENAI_API_KEY")
    github_token: SecretStr | None = Field(default=None, validation_alias="GITHUB_TOKEN")
    max_retries: int = Field(default=2, ge=0, le=5)
    retry_workspace_policy: Literal["preserve", "isolated"] = "preserve"
    patch_transactions: bool = False
    context_chars: int = Field(default=24000, ge=2000, le=100000)
    model_timeout: float = Field(default=45, ge=1, le=180)
    model_streaming: bool = False
    model_stream_usage: bool = True
    model_path_scope: bool = True
    model_min_interval: float = Field(default=0, ge=0, le=60)
    sandbox_image: str = "repopilot-sandbox:local"
    github_repository: str | None = None
    github_repository_subdirectory: str = ""
    github_base_branch: str | None = None
    test_timeout: int = Field(default=60, ge=1, le=300)
