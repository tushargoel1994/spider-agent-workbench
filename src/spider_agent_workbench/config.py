
# src/spider_agent_workbench

from pydantic_settings import BaseSettings, SettingsConfigDict
from spider_agent_workbench.paths import PROJECT_ROOT

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=PROJECT_ROOT/ ".env")
    model_provider: str
    anthropic_api_key: str | None = None
    anthropic_default_model: str
    deepseek_api_key: str | None = None
    deepseek_default_model: str

Settings = Settings()
