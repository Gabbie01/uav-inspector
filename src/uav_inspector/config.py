"""运行配置。

所有配置项都可通过环境变量或项目根目录的 .env 文件覆盖，
环境变量名见 .env.example。
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用配置。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    llm_base_url: str = "https://api.deepseek.com/v1"
    llm_api_key: SecretStr = SecretStr("")
    llm_model: str = "deepseek-chat"
    llm_timeout_s: float = Field(default=60.0, gt=0)
    llm_max_retries: int = Field(default=3, ge=1, le=10)
    llm_temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    log_level: str = "INFO"

    @field_validator("llm_base_url")
    @classmethod
    def _strip_trailing_slash(cls, value: str) -> str:
        return value.rstrip("/")

    @field_validator("log_level")
    @classmethod
    def _upper(cls, value: str) -> str:
        return value.upper()

    @property
    def has_api_key(self) -> bool:
        """是否已配置可用的 API Key。"""
        return bool(self.llm_api_key.get_secret_value().strip())


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """获取全局唯一的配置实例（带缓存，便于测试覆盖）。"""
    return Settings()
