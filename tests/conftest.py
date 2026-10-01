import asyncio
import os
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.pool import NullPool

from app.db import create_engine

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://timesheet:timesheet@localhost:5432/timesheet_test",
)


async def _ping(url: str) -> str | None:
    engine = create_engine(url, poolclass=NullPool, connect_args={"timeout": 3})
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return None
    except Exception as exc:  # noqa: BLE001 — любая ошибка подключения означает «БД недоступна»
        return f"{type(exc).__name__}: {exc}"
    finally:
        await engine.dispose()


@pytest.fixture(scope="session")
def database_url() -> str:
    """URL тестовой БД; все тесты, которые от неё зависят, пропускаются, если Postgres недоступен."""
    error = asyncio.run(_ping(TEST_DATABASE_URL))
    if error:
        pytest.skip(f"Тестовая БД недоступна ({TEST_DATABASE_URL}): {error}")
    return TEST_DATABASE_URL


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_engine(database_url, poolclass=NullPool)
    try:
        yield engine
    finally:
        await engine.dispose()
