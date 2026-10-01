"""Изоляция ошибки одного сообщения на настоящем Postgres.

Без savepoint ошибка SQL переводит всю транзакцию в состояние aborted и пачка не может закоммититься.
"""

from datetime import UTC, date, datetime, time

from sqlalchemy import text

from app.domain.models import Employee, Group, Message, MessageStatus
from app.repositories.attendance import SqlAttendanceRepository
from app.services.ingest import IngestService
from app.services.processing import ProcessingService

CHAT_ID = -1001234567890
DAY = date(2025, 9, 19)


async def test_sql_error_in_one_message_does_not_abort_batch(uow_factory, monkeypatch):
    async with uow_factory() as uow:
        await uow.groups.upsert(Group(CHAT_ID, "Пост 1", time(7, 0), time(10, 0)))
        for full_name, surname in [("Мехоношин А", "мехоношин"), ("Петров С", "петров"),
                                   ("Ёлкин О", "елкин")]:
            await uow.employees.add(Employee(None, full_name, surname))
        await uow.commit()

    ingest = IngestService(uow_factory)
    for message_id, caption in [(1, "Мехоношин"), (2, "Петров"), (3, "Ёлкин")]:
        await ingest.ingest(Message(CHAT_ID, message_id, datetime(2025, 9, 19, 5, 50, tzinfo=UTC),
                                    caption=caption))

    original = SqlAttendanceRepository.add_if_absent

    async def failing_for_petrov(self, attendance):
        created = await original(self, attendance)
        if attendance.employee_id == 2:
            await self._session.execute(text("SELECT 1 / 0"))
        return created

    monkeypatch.setattr(SqlAttendanceRepository, "add_if_absent", failing_for_petrov)

    assert await ProcessingService(uow_factory, batch_size=10).process_batch() == 3

    async with uow_factory() as uow:
        messages = {m.message_id: m for m in await uow.messages.list(None, limit=10, offset=0)}
        marks = await uow.attendance.list_between(DAY, DAY, chat_id=None)

    assert messages[1].status is MessageStatus.ACCEPTED
    assert messages[3].status is MessageStatus.ACCEPTED
    assert messages[2].status is MessageStatus.ERROR
    assert messages[2].reason.startswith("processing_error: DBAPIError")
    assert "division by zero" in messages[2].reason
    # Отметка упавшего сообщения откатилась вместе с savepoint.
    assert sorted(m.employee_id for m in marks) == [1, 3]
