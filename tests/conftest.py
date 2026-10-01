import asyncio
import os
from collections.abc import AsyncIterator
from functools import partial

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.pool import NullPool

from app.db import create_engine, create_session_factory
from app.repositories.orm import Base
from app.repositories.uow import SqlAlchemyUnitOfWork

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://timesheet:timesheet@localhost:5432/timesheet_test",
)


async def _prepare(url: str) -> str | None:
    """Проверить доступность БД и пересоздать схему; вернуть текст ошибки, если БД недоступна."""
    engine = create_engine(url, poolclass=NullPool, connect_args={"timeout": 3})
    try:
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        except Exception as exc:  # noqa: BLE001 — любая ошибка подключения = «БД недоступна»
            return f"{type(exc).__name__}: {exc}"
        # Ошибки схемы не глотаем: они должны ронять тесты, а не пропускать их.
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        return None
    finally:
        await engine.dispose()


@pytest.fixture(scope="session")
def database_url() -> str:
    """URL тестовой БД со свежей схемой; зависящие от неё тесты пропускаются, если Postgres недоступен."""
    error = asyncio.run(_prepare(TEST_DATABASE_URL))
    if error:
        pytest.skip(f"Тестовая БД недоступна ({TEST_DATABASE_URL}): {error}")
    return TEST_DATABASE_URL


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_engine(database_url, poolclass=NullPool)
    tables = ", ".join(table.name for table in Base.metadata.sorted_tables)
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
def uow_factory(engine: AsyncEngine):
    return partial(SqlAlchemyUnitOfWork, create_session_factory(engine))
