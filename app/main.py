"""Composition root: сборка зависимостей (db → UoW → сервисы → хендлеры) и lifespan."""

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from functools import partial

from aiogram import Bot
from fastapi import FastAPI

from app.config import Settings
from app.db import create_engine, create_session_factory
from app.handlers.telegram import create_dispatcher
from app.handlers.worker import run_worker
from app.repositories.orm import create_schema
from app.repositories.uow import SqlAlchemyUnitOfWork
from app.services.ingest import IngestService
from app.services.processing import ProcessingService

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Services:
    ingest: IngestService
    processing: ProcessingService


def _log_crash(task: asyncio.Task) -> None:
    if not task.cancelled() and task.exception() is not None:
        logger.error("background task %s crashed", task.get_name(), exc_info=task.exception())


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        logging.basicConfig(
            level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
        )
        engine = create_engine(settings.database_url)
        await create_schema(engine)
        uow_factory = partial(SqlAlchemyUnitOfWork, create_session_factory(engine))

        services = Services(
            ingest=IngestService(uow_factory),
            processing=ProcessingService(uow_factory, settings.batch_size),
        )
        app.state.services = services

        workers = [
            asyncio.create_task(
                run_worker(services.processing, settings.poll_interval), name=f"worker-{i}"
            )
            for i in range(settings.workers)
        ]
        for task in workers:
            task.add_done_callback(_log_crash)

        dispatcher, polling = None, None
        if settings.bot_tokens:
            dispatcher = create_dispatcher(services.ingest)
            bots = [Bot(token) for token in settings.bot_tokens]
            polling = asyncio.create_task(
                dispatcher.start_polling(*bots, handle_signals=False, allowed_updates=["message"]),
                name="telegram-polling",
            )
            polling.add_done_callback(_log_crash)
        else:
            logger.warning("BOT_TOKENS is empty: Telegram polling disabled")

        try:
            yield
        finally:
            if polling is not None:
                # Сначала перестаём принимать апдейты; поллинг сам закроет сессии ботов.
                if not polling.done():
                    with contextlib.suppress(RuntimeError):
                        await dispatcher.stop_polling()
                await asyncio.gather(polling, return_exceptions=True)
            for task in workers:
                task.cancel()
            await asyncio.gather(*workers, return_exceptions=True)
            await engine.dispose()

    return FastAPI(title="Shift timesheet", lifespan=lifespan)
