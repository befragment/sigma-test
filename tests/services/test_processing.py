from datetime import UTC, date, datetime, time

import pytest

from app.domain.models import Group, Message, MessageStatus, Reason
from app.services.processing import ProcessingService
from tests.fakes import FakeDB

CHAT_ID = -1001
DAY = date(2025, 9, 19)
NOW = datetime(2025, 9, 19, 12, 0, tzinfo=UTC)
# 05:50 UTC = 08:50 МСК, внутри окна 07:00–10:00
SENT_AT = datetime(2025, 9, 19, 5, 50, tzinfo=UTC)


@pytest.fixture
def db() -> FakeDB:
    db = FakeDB()
    db.add_group(Group(CHAT_ID, "Пост 1", time(7, 0), time(10, 0)))
    return db


@pytest.fixture
def service(db: FakeDB) -> ProcessingService:
    return ProcessingService(db.uow, batch_size=10, clock=lambda: NOW)


def put(db: FakeDB, caption: str | None, *, message_id: int | None = None, tg_user_id: int = 777,
        chat_id: int = CHAT_ID, sent_at: datetime = SENT_AT) -> int:
    """Положить сообщение в очередь (status=new), вернуть его id."""
    id = db.next_id()
    db.state.messages[id] = Message(
        id=id, chat_id=chat_id, message_id=message_id or id, sent_at=sent_at,
        tg_user_id=tg_user_id, caption=caption,
    )
    return id


def stored(db: FakeDB, id: int) -> Message:
    return db.state.messages[id]


async def test_accepted_message_creates_attendance(db, service):
    employee = db.add_employee("Мехоношин Алексей", "мехоношин")
    id = put(db, "Мехоношин")

    assert await service.process_batch() == 1

    message = stored(db, id)
    assert (message.status, message.reason) == (MessageStatus.ACCEPTED, Reason.BY_CAPTION)
    assert (message.employee_id, message.shift_date, message.processed_at) == (employee.id, DAY, NOW)
    [mark] = db.state.attendance.values()
    assert (mark.employee_id, mark.shift_date, mark.message_id, mark.manual) == (
        employee.id, DAY, id, False,
    )
    assert db.commits == 1


async def test_binding_is_used_for_empty_caption(db, service):
    employee = db.add_employee("Петров Сергей", "петров")
    db.bind(tg_user_id=555, employee_id=employee.id)
    id = put(db, None, tg_user_id=555)

    await service.process_batch()

    assert stored(db, id).reason == Reason.BY_ACCOUNT
    assert (employee.id, DAY) in db.state.attendance


async def test_duplicate_within_one_batch(db, service):
    employee = db.add_employee("Мехоношин Алексей", "мехоношин")
    first, second = put(db, "Мехоношин"), put(db, "Мехоношин снова")

    assert await service.process_batch() == 2

    assert stored(db, first).status is MessageStatus.ACCEPTED
    assert (stored(db, second).status, stored(db, second).reason) == (
        MessageStatus.DUPLICATE, Reason.ALREADY_MARKED,
    )
    # Дубль сохраняет сотрудника и дату — по ним видна история.
    assert (stored(db, second).employee_id, stored(db, second).shift_date) == (employee.id, DAY)
    assert len(db.state.attendance) == 1
    assert db.state.attendance[(employee.id, DAY)].message_id == first


async def test_duplicate_across_batches(db, service):
    db.add_employee("Мехоношин Алексей", "мехоношин")
    put(db, "Мехоношин")
    await service.process_batch()
    later = put(db, "Мехоношин", sent_at=datetime(2025, 9, 19, 6, 30, tzinfo=UTC))

    await service.process_batch()

    assert stored(db, later).status is MessageStatus.DUPLICATE
    assert len(db.state.attendance) == 1


async def test_processed_messages_are_not_taken_again(db, service):
    db.add_employee("Мехоношин Алексей", "мехоношин")
    put(db, "Мехоношин")

    assert await service.process_batch() == 1
    assert await service.process_batch() == 0
    assert len(db.state.attendance) == 1


async def test_manual_review_keeps_shift_date_without_attendance(db, service):
    db.add_employee("Иванов Иван", "иванов")
    db.add_employee("Иванов Пётр", "иванов")
    id = put(db, "Иванов")

    await service.process_batch()

    message = stored(db, id)
    assert (message.status, message.reason) == (MessageStatus.MANUAL_REVIEW, Reason.AMBIGUOUS_SURNAME)
    assert message.shift_date == DAY
    assert message.employee_id is None
    assert db.state.attendance == {}


async def test_unknown_group_rejected(db, service):
    db.add_employee("Мехоношин Алексей", "мехоношин")
    id = put(db, "Мехоношин", chat_id=-999)

    await service.process_batch()

    assert (stored(db, id).status, stored(db, id).reason) == (
        MessageStatus.REJECTED, Reason.UNKNOWN_GROUP,
    )
    assert db.state.attendance == {}


async def test_error_in_one_message_does_not_break_batch(db, service):
    mekhonoshin = db.add_employee("Мехоношин Алексей", "мехоношин")
    petrov = db.add_employee("Петров Сергей", "петров")
    elkin = db.add_employee("Ёлкин Олег", "елкин")
    ok_before, broken, ok_after = put(db, "Мехоношин"), put(db, "Петров"), put(db, "Ёлкин")
    db.fail_attendance_for = {broken}

    assert await service.process_batch() == 3

    assert stored(db, ok_before).status is MessageStatus.ACCEPTED
    assert stored(db, ok_after).status is MessageStatus.ACCEPTED
    failed = stored(db, broken)
    assert failed.status is MessageStatus.ERROR
    assert failed.reason == "processing_error: RuntimeError: boom"
    assert (failed.employee_id, failed.shift_date, failed.processed_at) == (None, None, NOW)
    # Частичная запись упавшего сообщения откатилась вместе с его savepoint.
    assert set(db.state.attendance) == {(mekhonoshin.id, DAY), (elkin.id, DAY)}
    assert (petrov.id, DAY) not in db.state.attendance


async def test_batch_failure_rolls_back_and_keeps_messages_new(db, service):
    db.add_employee("Мехоношин Алексей", "мехоношин")
    id = put(db, "Мехоношин")
    db.fail_groups_list = True

    with pytest.raises(ConnectionError):
        await service.process_batch()

    assert stored(db, id).status is MessageStatus.NEW
    assert db.state.attendance == {}

    db.fail_groups_list = False
    assert await service.process_batch() == 1
    assert stored(db, id).status is MessageStatus.ACCEPTED


async def test_batch_size_is_respected(db):
    db.add_employee("Мехоношин Алексей", "мехоношин")
    ids = [put(db, "Мехоношин") for _ in range(5)]
    service = ProcessingService(db.uow, batch_size=2, clock=lambda: NOW)

    assert await service.process_batch() == 2

    assert [stored(db, id).status for id in ids].count(MessageStatus.NEW) == 3
    # Пачка берётся по возрастанию id.
    assert stored(db, ids[0]).status is MessageStatus.ACCEPTED
