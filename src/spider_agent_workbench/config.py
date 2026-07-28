
# src/spider_agent_workbench

from pydantic_settings import BaseSettings, SettingsConfigDict
from spider_agent_workbench.paths import PROJECT_ROOT

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=PROJECT_ROOT/ ".env")
    anthropic_api_key: str

Settings = Settings()
