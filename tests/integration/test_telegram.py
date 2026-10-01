"""Сквозной тест Telegram-хендлера: имитированный Update → Dispatcher → messages → воркер → attendance.

Сеть не нужна: feed_update прогоняет апдейт через роутер, хендлер не вызывает Bot API.
"""

from datetime import UTC, date, datetime, time

import pytest
from aiogram import Bot
from aiogram.types import Chat, PhotoSize, Update, User
from aiogram.types import Message as TgMessage

from app.domain.models import Employee, Group, MessageStatus
from app.handlers.telegram import create_dispatcher
from app.services.ingest import IngestService
from app.services.processing import ProcessingService

CHAT_ID = -1001234567890
PHOTO = [PhotoSize(file_id="f", file_unique_id="u", width=1280, height=960)]


def update(update_id: int, *, chat_type: str = "supergroup", photo=PHOTO, text: str | None = None,
           caption: str | None = "Мехоношин", message_id: int | None = None) -> Update:
    return Update(
        update_id=update_id,
        message=TgMessage(
            message_id=message_id or update_id,
            # 05:50:06 UTC = 08:50:06 МСК — пример из ТЗ
            date=datetime(2025, 9, 19, 5, 50, 6, tzinfo=UTC),
            chat=Chat(id=CHAT_ID if chat_type != "private" else 777, type=chat_type, title="Пост 1"),
            from_user=User(id=777, is_bot=False, first_name="Алексей"),
            photo=photo,
            caption=caption if photo else None,
            text=text,
            media_group_id=None,
        ),
    )


@pytest.fixture
async def bot():
    bot = Bot("123456:TEST-TOKEN")
    yield bot
    await bot.session.close()


async def test_photo_update_becomes_attendance(uow_factory, bot):
    async with uow_factory() as uow:
        await uow.groups.upsert(Group(CHAT_ID, "Пост 1", time(7, 0), time(10, 0)))
        employee = await uow.employees.add(Employee(None, "Мехоношин Алексей", "мехоношин"))
        await uow.commit()
    dispatcher = create_dispatcher(IngestService(uow_factory))

    await dispatcher.feed_update(bot, update(1))
    await dispatcher.feed_update(bot, update(2, message_id=1))  # повторная доставка того же сообщения
    await dispatcher.feed_update(bot, update(3, photo=None, text="Мехоношин"))  # текст без фото
    await dispatcher.feed_update(bot, update(4, chat_type="private"))  # фото в личке боту
    await dispatcher.feed_update(bot, update(5, chat_type="channel"))  # пост в канале

    async with uow_factory() as uow:
        [stored] = await uow.messages.list(None, limit=10, offset=0)
    assert (stored.chat_id, stored.message_id, stored.tg_user_id, stored.caption) == (
        CHAT_ID, 1, 777, "Мехоношин",
    )
    assert stored.sent_at == datetime(2025, 9, 19, 5, 50, 6, tzinfo=UTC)
    assert stored.status is MessageStatus.NEW

    assert await ProcessingService(uow_factory, batch_size=10).process_batch() == 1

    async with uow_factory() as uow:
        [mark] = await uow.attendance.list_between(date(2025, 9, 19), date(2025, 9, 19), CHAT_ID)
    assert (mark.employee_id, mark.message_id) == (employee.id, stored.id)
