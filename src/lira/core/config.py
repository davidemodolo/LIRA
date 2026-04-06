from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    llm_provider: Literal["ollama", "groq"] = "ollama"
    llm_model: str = "gemma4:e4b"

    groq_api_key: str | None = None

    ollama_base_url: str = "http://localhost:11434"
    ollama_keep_alive: str = "30m"

    agent_max_iterations: int = 10
    agent_timeout: int | None = None
    agent_temperature: float = 0.7
    agent_max_context_tokens: int = 8192

    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_reload: bool = False

    # Remote API URL — when set, the CLI forwards messages to the running
    # L.I.R.A. server instead of running a local agent.
    # Set via env var LIRA_API_URL, e.g. "http://homeserver:8001"
    api_url: str | None = None

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


settings = Settings()
