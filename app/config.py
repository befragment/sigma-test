from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://timesheet:timesheet@localhost:5432/timesheet"
    # Несколько ботов через запятую; пустое значение — сервис работает без поллинга.
    bot_tokens: Annotated[list[str], NoDecode] = []
    admin_token: str
    workers: int = 2
    batch_size: int = 100
    # Пауза воркера, когда очередь пуста, в секундах.
    poll_interval: float = 1.0
    log_level: str = "INFO"

    @field_validator("bot_tokens", mode="before")
    @classmethod
    def split_tokens(cls, value: object) -> object:
        if isinstance(value, str):
            return [token.strip() for token in value.split(",") if token.strip()]
        return value
