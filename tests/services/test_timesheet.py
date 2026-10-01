from datetime import date, time

import pytest

from app.domain.errors import NotFound, ValidationError
from app.domain.models import Attendance, Group, Message, MessageStatus
from app.services.timesheet import TimesheetService
from tests.fakes import FakeDB


@pytest.fixture
def db() -> FakeDB:
    db = FakeDB()
    db.add_group(Group(-1, "Пост 1", time(7, 0), time(10, 0)))
    db.add_group(Group(-2, "Пост 2", time(7, 0), time(10, 0)))
    return db


def add_mark(db: FakeDB, employee_id: int, day: date, chat_id: int) -> None:
    id = db.next_id()
    db.state.messages[id] = Message(chat_id, id, None, id=id, status=MessageStatus.ACCEPTED)
    db.state.attendance[(employee_id, day)] = Attendance(employee_id, day, id)


async def test_month_bounds_and_all_employees(db):
    petrov = db.add_employee("Петров Сергей", "петров")
    db.add_employee("Антонов Иван", "антонов")
    add_mark(db, petrov.id, date(2025, 9, 1), -1)
    add_mark(db, petrov.id, date(2025, 9, 30), -2)
    add_mark(db, petrov.id, date(2025, 10, 1), -1)
    add_mark(db, petrov.id, date(2025, 8, 31), -1)

    sheet = await TimesheetService(db.uow).get("2025-09")

    assert [(r.full_name, set(r.days)) for r in sheet.rows] == [
        ("Антонов Иван", set()), ("Петров Сергей", {1, 30}),
    ]


async def test_group_filter(db):
    petrov = db.add_employee("Петров Сергей", "петров")
    antonov = db.add_employee("Антонов Иван", "антонов")
    add_mark(db, petrov.id, date(2025, 9, 1), -1)
    add_mark(db, antonov.id, date(2025, 9, 2), -2)

    sheet = await TimesheetService(db.uow).get("2025-09", chat_id=-1)

    assert [(r.full_name, set(r.days)) for r in sheet.rows] == [("Петров Сергей", {1})]
    assert sheet.title.endswith("Пост 1")


async def test_unknown_group(db):
    with pytest.raises(NotFound):
        await TimesheetService(db.uow).get("2025-09", chat_id=-999)


async def test_bad_month(db):
    with pytest.raises(ValidationError):
        await TimesheetService(db.uow).get("2025-13")


async def test_xlsx_bytes(db):
    content = await TimesheetService(db.uow).get_xlsx("2025-09")
    assert content[:2] == b"PK"  # zip-контейнер xlsx
