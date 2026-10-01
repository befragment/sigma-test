"""Ручная проверка на реальном Postgres: одновременные решения по одному сообщению."""

import asyncio
from datetime import UTC, date, datetime, time

import pytest

from app.domain.errors import InvalidState
from app.domain.models import Employee, Group, Message, MessageStatus
from app.services.ingest import IngestService
from app.services.processing import ProcessingService
from app.services.review import ReviewService

CHAT_ID = -1001234567890


async def test_concurrent_approvals_mark_once(uow_factory):
    async with uow_factory() as uow:
        await uow.groups.upsert(Group(CHAT_ID, "Пост 1", time(7, 0), time(10, 0)))
        first = await uow.employees.add(Employee(None, "Иванов Иван", "иванов"))
        second = await uow.employees.add(Employee(None, "Иванов Пётр", "иванов"))
        await uow.commit()
    await IngestService(uow_factory).ingest(
        Message(CHAT_ID, 1, datetime(2025, 9, 19, 5, 50, tzinfo=UTC), caption="Иванов")
    )
    await ProcessingService(uow_factory, batch_size=10).process_batch()
    service = ReviewService(uow_factory)
    [message] = await service.list_review()

    results = await asyncio.gather(
        service.approve(message.id, first.id),
        service.approve(message.id, second.id),
        service.reject(message.id),
        return_exceptions=True,
    )

    decided = [r for r in results if isinstance(r, Message)]
    assert len(decided) == 1
    assert all(isinstance(r, InvalidState) for r in results if r not in decided)
    async with uow_factory() as uow:
        marks = await uow.attendance.list_between(date(2025, 9, 19), date(2025, 9, 19), None)
    expected_marks = 0 if decided[0].status is MessageStatus.REJECTED else 1
    assert len(marks) == expected_marks
    with pytest.raises(InvalidState):
        await service.reject(message.id)
