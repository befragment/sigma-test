"""Сквозной путь на реальном Postgres: фото с фамилией → единица в attendance."""

import asyncio
from datetime import UTC, date, datetime, time

from app.config import Settings
from app.domain.models import Employee, Group, Message, MessageStatus, Reason
from app.main import create_app
from app.services.ingest import IngestService
from app.services.processing import ProcessingService

CHAT_ID = -1001234567890
SHIFT_DAY = date(2025, 9, 19)


async def seed(uow_factory) -> int:
    async with uow_factory() as uow:
        await uow.groups.upsert(Group(CHAT_ID, "Пост 1", time(7, 0), time(10, 0)))
        employee = await uow.employees.add(Employee(None, "Мехоношин Алексей", "мехоношин"))
        await uow.commit()
    return employee.id


def photo(message_id: int = 10, caption: str | None = "Мехоношин") -> Message:
    # 05:50:06 UTC = 08:50:06 по Москве — пример из ТЗ
    return Message(
        chat_id=CHAT_ID,
        message_id=message_id,
        sent_at=datetime(2025, 9, 19, 5, 50, 6, tzinfo=UTC),
        tg_user_id=777,
        caption=caption,
    )


async def test_photo_with_surname_becomes_attendance(uow_factory):
    employee_id = await seed(uow_factory)

    assert await IngestService(uow_factory).ingest(photo()) is True
    assert await ProcessingService(uow_factory, batch_size=10).process_batch() == 1

    async with uow_factory() as uow:
        marks = await uow.attendance.list_between(SHIFT_DAY, SHIFT_DAY, chat_id=CHAT_ID)
        [message] = await uow.messages.list(status=None, limit=10, offset=0)

    assert [(m.employee_id, m.shift_date, m.message_id, m.manual) for m in marks] == [
        (employee_id, SHIFT_DAY, message.id, False)
    ]
    assert message.status is MessageStatus.ACCEPTED
    assert message.reason == Reason.BY_CAPTION
    assert message.employee_id == employee_id
    assert message.shift_date == SHIFT_DAY
    assert message.processed_at is not None


async def test_empty_queue_returns_zero(uow_factory):
    assert await ProcessingService(uow_factory, batch_size=10).process_batch() == 0


async def test_app_lifespan_workers_process_queue(database_url, uow_factory):
    """Composition root: lifespan поднимает воркеры, которые сами разбирают очередь."""
    employee_id = await seed(uow_factory)
    settings = Settings(
        _env_file=None,
        database_url=database_url,
        admin_token="test",
        bot_tokens="",
        workers=2,
        poll_interval=0.05,
    )
    app = create_app(settings)

    async with app.router.lifespan_context(app):
        await app.state.services.ingest.ingest(photo())
        for _ in range(100):
            async with uow_factory() as uow:
                [message] = await uow.messages.list(status=None, limit=1, offset=0)
            if message.status is not MessageStatus.NEW:
                break
            await asyncio.sleep(0.05)

    assert message.status is MessageStatus.ACCEPTED
    assert message.employee_id == employee_id
