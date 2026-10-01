from datetime import UTC, date, datetime, time

import pytest

from app.domain.errors import InvalidState, NotFound, ValidationError
from app.domain.models import Attendance, Group, Message, MessageStatus, Reason
from app.services.review import ReviewService
from tests.fakes import FakeDB

CHAT_ID = -1001
DAY = date(2025, 9, 19)
NOW = datetime(2025, 9, 19, 12, 0, tzinfo=UTC)


@pytest.fixture
def db() -> FakeDB:
    db = FakeDB()
    db.add_group(Group(CHAT_ID, "Пост 1", time(7, 0), time(10, 0)))
    return db


@pytest.fixture
def service(db: FakeDB) -> ReviewService:
    return ReviewService(db.uow, clock=lambda: NOW)


def put(db: FakeDB, status: MessageStatus = MessageStatus.MANUAL_REVIEW,
        reason: str = Reason.EMPLOYEE_NOT_FOUND.value, shift_date: date | None = DAY) -> int:
    id = db.next_id()
    db.state.messages[id] = Message(
        id=id, chat_id=CHAT_ID, message_id=id, sent_at=datetime(2025, 9, 19, 5, 50, tzinfo=UTC),
        caption="на посту", status=status, reason=reason, shift_date=shift_date,
    )
    return id


async def test_list_review_returns_only_manual_review(db, service):
    review_id = put(db)
    put(db, status=MessageStatus.ACCEPTED, reason=Reason.BY_CAPTION.value)
    put(db, status=MessageStatus.REJECTED, reason=Reason.OUTSIDE_WINDOW.value)

    assert [m.id for m in await service.list_review()] == [review_id]


class TestApprove:
    async def test_creates_manual_attendance(self, db, service):
        employee = db.add_employee("Иванов Иван", "иванов")
        id = put(db)

        message = await service.approve(id, employee.id)

        assert (message.status, message.reason) == (MessageStatus.ACCEPTED, Reason.MANUAL_APPROVED)
        assert (message.employee_id, message.shift_date, message.processed_at) == (employee.id, DAY, NOW)
        assert db.state.messages[id] == message
        mark = db.state.attendance[(employee.id, DAY)]
        assert (mark.message_id, mark.manual) == (id, True)

    async def test_explicit_shift_date_overrides_calculated(self, db, service):
        employee = db.add_employee("Иванов Иван", "иванов")
        id = put(db)

        message = await service.approve(id, employee.id, shift_date=date(2025, 9, 18))

        assert message.shift_date == date(2025, 9, 18)
        assert set(db.state.attendance) == {(employee.id, date(2025, 9, 18))}

    async def test_existing_mark_gives_duplicate(self, db, service):
        employee = db.add_employee("Иванов Иван", "иванов")
        earlier = put(db, status=MessageStatus.ACCEPTED, reason=Reason.BY_CAPTION.value)
        db.state.attendance[(employee.id, DAY)] = Attendance(employee.id, DAY, earlier)
        id = put(db)

        message = await service.approve(id, employee.id)

        assert (message.status, message.reason) == (MessageStatus.DUPLICATE, Reason.ALREADY_MARKED)
        assert db.state.attendance[(employee.id, DAY)].message_id == earlier

    async def test_without_any_shift_date(self, db, service):
        employee = db.add_employee("Иванов Иван", "иванов")
        id = put(db, shift_date=None)

        with pytest.raises(ValidationError):
            await service.approve(id, employee.id)
        assert db.state.messages[id].status is MessageStatus.MANUAL_REVIEW

    @pytest.mark.parametrize("status", [MessageStatus.ACCEPTED, MessageStatus.REJECTED,
                                        MessageStatus.DUPLICATE, MessageStatus.NEW, MessageStatus.ERROR])
    async def test_only_manual_review_can_be_approved(self, db, service, status):
        employee = db.add_employee("Иванов Иван", "иванов")
        id = put(db, status=status)

        with pytest.raises(InvalidState):
            await service.approve(id, employee.id)
        assert db.state.attendance == {}

    async def test_unknown_message(self, db, service):
        employee = db.add_employee("Иванов Иван", "иванов")
        with pytest.raises(NotFound):
            await service.approve(999, employee.id)

    async def test_unknown_employee(self, db, service):
        id = put(db)
        with pytest.raises(NotFound):
            await service.approve(id, 999)
        assert db.state.messages[id].status is MessageStatus.MANUAL_REVIEW

    async def test_inactive_employee(self, db, service):
        employee = db.add_employee("Сидоров Павел", "сидоров", active=False)
        id = put(db)
        with pytest.raises(ValidationError):
            await service.approve(id, employee.id)
        assert db.state.attendance == {}


class TestReject:
    async def test_reject(self, db, service):
        id = put(db)

        message = await service.reject(id)

        assert (message.status, message.reason, message.processed_at) == (
            MessageStatus.REJECTED, Reason.MANUAL_REJECTED, NOW,
        )
        assert message.shift_date == DAY  # рассчитанная дата остаётся для журнала
        assert db.state.messages[id].status is MessageStatus.REJECTED
        assert db.state.attendance == {}

    async def test_second_decision_is_conflict(self, db, service):
        employee = db.add_employee("Иванов Иван", "иванов")
        id = put(db)
        await service.reject(id)

        with pytest.raises(InvalidState):
            await service.reject(id)
        with pytest.raises(InvalidState):
            await service.approve(id, employee.id)
