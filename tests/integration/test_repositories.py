"""Интеграционные тесты репозиториев и конкурентной обработки на реальном Postgres."""

import asyncio
import contextlib
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import func, select

from app.domain.models import Attendance, Binding, Employee, Group, Message, MessageStatus, Reason
from app.repositories.attendance import SqlAttendanceRepository
from app.repositories.orm import AttendanceRow, MessageRow
from app.services.ingest import IngestService
from app.services.processing import ProcessingService

CHAT_ID = -1001234567890
DAY = date(2025, 9, 19)
SENT_AT = datetime(2025, 9, 19, 5, 50, tzinfo=UTC)  # 08:50 МСК


def photo(message_id: int, caption: str | None = "Мехоношин", sent_at: datetime = SENT_AT) -> Message:
    return Message(CHAT_ID, message_id, sent_at, tg_user_id=777, caption=caption)


async def count(engine, model) -> int:
    async with engine.connect() as conn:
        return await conn.scalar(select(func.count()).select_from(model))


async def seed_employees(uow_factory, surnames: list[str]) -> list[int]:
    async with uow_factory() as uow:
        await uow.groups.upsert(Group(CHAT_ID, "Пост 1", time(7, 0), time(10, 0)))
        ids = [(await uow.employees.add(Employee(None, f"{s} И.И.", s.lower()))).id for s in surnames]
        await uow.commit()
    return ids


class TestIngestIdempotency:
    async def test_same_message_stored_once(self, uow_factory, engine):
        ingest = IngestService(uow_factory)

        assert await ingest.ingest(photo(1)) is True
        assert await ingest.ingest(photo(1, caption="изменённая подпись")) is False

        assert await count(engine, MessageRow) == 1
        async with uow_factory() as uow:
            [stored] = await uow.messages.list(None, limit=10, offset=0)
        assert stored.caption == "Мехоношин"

    async def test_same_message_id_in_other_chat_is_different(self, uow_factory, engine):
        ingest = IngestService(uow_factory)
        await ingest.ingest(photo(1))
        await ingest.ingest(Message(-1009999, 1, SENT_AT, caption="Мехоношин"))
        assert await count(engine, MessageRow) == 2

    async def test_concurrent_delivery_from_several_bots(self, uow_factory, engine):
        """Несколько ботов в одной группе получают одно и то же сообщение одновременно."""
        ingest = IngestService(uow_factory)

        results = await asyncio.gather(*(ingest.ingest(photo(1)) for _ in range(10)))

        assert results.count(True) == 1
        assert await count(engine, MessageRow) == 1


class TestAttendanceUniqueness:
    async def test_second_mark_for_same_day_is_ignored(self, uow_factory, engine):
        [employee_id] = await seed_employees(uow_factory, ["Мехоношин"])
        await IngestService(uow_factory).ingest(photo(1))
        async with uow_factory() as uow:
            [message] = await uow.messages.list(None, limit=1, offset=0)
            mark = Attendance(employee_id, DAY, message.id)
            assert await uow.attendance.add_if_absent(mark) is True
            assert await uow.attendance.add_if_absent(mark) is False
            assert await uow.attendance.add_if_absent(
                Attendance(employee_id, DAY + timedelta(days=1), message.id)
            ) is True
            await uow.commit()
        assert await count(engine, AttendanceRow) == 2

    async def test_concurrent_insert_waits_for_first_transaction(self, uow_factory):
        [employee_id] = await seed_employees(uow_factory, ["Мехоношин"])
        await IngestService(uow_factory).ingest(photo(1))
        async with uow_factory() as uow:
            [message] = await uow.messages.list(None, limit=1, offset=0)
        mark = Attendance(employee_id, DAY, message.id)

        async with uow_factory() as first, uow_factory() as second:
            assert await first.attendance.add_if_absent(mark) is True
            pending = asyncio.create_task(second.attendance.add_if_absent(mark))
            await asyncio.sleep(0.2)
            assert not pending.done()  # ждёт исхода первой транзакции на уникальном индексе
            await first.commit()
            assert await pending is False

    async def test_duplicate_photo_same_day_through_processing(self, uow_factory, engine):
        [employee_id] = await seed_employees(uow_factory, ["Мехоношин"])
        ingest = IngestService(uow_factory)
        await ingest.ingest(photo(1))
        await ingest.ingest(photo(2, sent_at=SENT_AT + timedelta(minutes=20)))

        await ProcessingService(uow_factory, batch_size=10).process_batch()

        async with uow_factory() as uow:
            messages = {m.message_id: m for m in await uow.messages.list(None, 10, 0)}
            [mark] = await uow.attendance.list_between(DAY, DAY, chat_id=CHAT_ID)
        assert messages[1].status is MessageStatus.ACCEPTED
        assert (messages[2].status, messages[2].reason) == (
            MessageStatus.DUPLICATE, Reason.ALREADY_MARKED,
        )
        assert (mark.employee_id, mark.message_id) == (employee_id, messages[1].id)


class TestQueue:
    async def test_skip_locked_gives_disjoint_batches(self, uow_factory):
        ingest = IngestService(uow_factory)
        for message_id in range(1, 8):
            await ingest.ingest(photo(message_id))

        async with uow_factory() as first, uow_factory() as second:
            batch1 = await first.messages.take_new_batch(5)
            batch2 = await second.messages.take_new_batch(5)

        assert [m.message_id for m in batch1] == [1, 2, 3, 4, 5]
        assert [m.message_id for m in batch2] == [6, 7]

    async def test_lock_released_after_rollback(self, uow_factory):
        await IngestService(uow_factory).ingest(photo(1))
        async with uow_factory() as uow:
            assert len(await uow.messages.take_new_batch(5)) == 1
        async with uow_factory() as uow:
            assert len(await uow.messages.take_new_batch(5)) == 1

    async def test_two_parallel_workers_process_each_message_once(self, uow_factory, engine):
        employees = await seed_employees(uow_factory, [f"Сотрудник{chr(0x430 + i)}" for i in range(20)])
        ingest = IngestService(uow_factory)
        # 200 сообщений: 20 сотрудников × 2 дня × 5 фото, порядок перемешан — пачки воркеров
        # пересекаются по сотрудникам и в них много дублей.
        expected_pairs = set()
        for n in range(200):
            employee_index = (n * 7) % 20
            day_offset = (n // 20) % 2
            surname = f"Сотрудник{chr(0x430 + employee_index)}"
            await ingest.ingest(photo(n + 1, caption=surname, sent_at=SENT_AT + timedelta(days=day_offset)))
            expected_pairs.add((employees[employee_index], DAY + timedelta(days=day_offset)))

        processed = {"a": 0, "b": 0}

        async def worker(name: str) -> None:
            service = ProcessingService(uow_factory, batch_size=7)
            while (n := await service.process_batch()) > 0:
                processed[name] += n

        await asyncio.gather(worker("a"), worker("b"))

        assert processed["a"] + processed["b"] == 200  # никто не обработан дважды
        assert processed["a"] > 0 and processed["b"] > 0  # работали оба
        async with uow_factory() as uow:
            messages = await uow.messages.list(None, limit=1000, offset=0)
            marks = await uow.attendance.list_between(DAY, DAY + timedelta(days=1), chat_id=None)
        statuses = [m.status for m in messages]
        assert statuses.count(MessageStatus.ACCEPTED) == len(expected_pairs) == 40
        assert statuses.count(MessageStatus.DUPLICATE) == 160
        assert {(m.employee_id, m.shift_date) for m in marks} == expected_pairs
        assert len(marks) == 40
        accepted_ids = {m.id for m in messages if m.status is MessageStatus.ACCEPTED}
        assert {m.message_id for m in marks} == accepted_ids


async def test_crossed_lock_order_does_not_deadlock(uow_factory, monkeypatch):
    """Пачки двух воркеров содержат тех же сотрудников в обратном порядке.

    Если ставить отметки в порядке сообщений, транзакции ждут друг друга на уникальном индексе
    attendance → Postgres обрывает одну из них (deadlock detected) и сообщение получает error.
    """
    first_id, second_id = await seed_employees(uow_factory, ["Первов", "Вторых"])
    ingest = IngestService(uow_factory)
    for message_id, caption in [(1, "Первов"), (2, "Вторых"), (3, "Вторых"), (4, "Первов")]:
        await ingest.ingest(photo(message_id, caption=caption))

    # Обе транзакции ставят по одной отметке и встречаются, прежде чем ставить вторую.
    barrier = asyncio.Barrier(2)
    original = SqlAttendanceRepository.add_if_absent

    async def add_then_meet(self, attendance):
        created = await original(self, attendance)
        if not getattr(self, "_met", False):
            self._met = True
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(barrier.wait(), timeout=1)
        return created

    monkeypatch.setattr(SqlAttendanceRepository, "add_if_absent", add_then_meet)

    async def first_worker():
        return await ProcessingService(uow_factory, batch_size=2).process_batch()

    async def second_worker():
        await asyncio.sleep(0.1)  # пусть первый заберёт сообщения 1–2
        return await ProcessingService(uow_factory, batch_size=2).process_batch()

    assert await asyncio.gather(first_worker(), second_worker()) == [2, 2]

    async with uow_factory() as uow:
        messages = await uow.messages.list(None, limit=10, offset=0)
        marks = await uow.attendance.list_between(DAY, DAY, chat_id=None)
    assert [m for m in messages if m.status is MessageStatus.ERROR] == []
    assert sorted(m.status for m in messages).count(MessageStatus.ACCEPTED) == 2
    assert {m.employee_id for m in marks} == {first_id, second_id}


class TestDirectory:
    async def test_group_upsert_updates_existing(self, uow_factory):
        async with uow_factory() as uow:
            await uow.groups.upsert(Group(CHAT_ID, "Старое", time(7, 0), time(10, 0)))
            await uow.groups.list()  # объект попадает в identity map сессии
            updated = await uow.groups.upsert(
                Group(CHAT_ID, "Новое", time(20, 0), time(8, 0), tz="Asia/Novosibirsk", active=False)
            )
            await uow.commit()
        async with uow_factory() as uow:
            assert await uow.groups.list() == [updated]
        assert (updated.title, updated.window_start, updated.tz, updated.active) == (
            "Новое", time(20, 0), "Asia/Novosibirsk", False,
        )

    async def test_binding_set_replaces_employee(self, uow_factory):
        first_id, second_id = await seed_employees(uow_factory, ["Первов", "Вторых"])
        async with uow_factory() as uow:
            await uow.bindings.set(Binding(555, first_id))
            await uow.bindings.set(Binding(555, second_id))
            await uow.commit()
        async with uow_factory() as uow:
            assert await uow.bindings.list() == [Binding(555, second_id)]
