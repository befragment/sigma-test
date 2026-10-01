from collections.abc import AsyncIterator

import httpx
import pytest
from fastapi import FastAPI

from app.config import Settings
from app.main import create_app

ADMIN_TOKEN = "test-admin-token"


@pytest.fixture
async def app(database_url: str, engine) -> AsyncIterator[FastAPI]:
    """Приложение на тестовой БД (engine очищает таблицы); воркеров и бота нет — очередь разбирают тесты."""
    settings = Settings(
        _env_file=None,
        database_url=database_url,
        admin_token=ADMIN_TOKEN,
        bot_tokens="",
        workers=0,
    )
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        yield app


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", headers={"X-Admin-Token": ADMIN_TOKEN}
    ) as client:
        yield client
