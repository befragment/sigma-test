"""Composition root: сборка зависимостей и lifespan.

На шаге 1 — только каркас приложения; сборка db → UoW → сервисы → хендлеры добавляется на шаге 3.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import Settings
from app.db import create_engine


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        logging.basicConfig(level=settings.log_level)
        engine = create_engine(settings.database_url)
        app.state.settings = settings
        app.state.engine = engine
        try:
            yield
        finally:
            await engine.dispose()

    return FastAPI(title="Shift timesheet", lifespan=lifespan)

