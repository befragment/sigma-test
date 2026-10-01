"""In-memory реализации репозиториев и Unit of Work для тестов сервисов.

Транзакции имитируются снимками состояния: без commit() изменения откатываются при выходе из UoW,
savepoint откатывает только свои изменения. Блокировок нет — конкурентность проверяется на Postgres.
"""

import copy
import itertools
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime
from typing import Self

from app.domain.errors import NotFound
from app.domain.models import Attendance, Binding, Employee, Group, Message, MessageStatus


@dataclass
class State:
    groups: dict[int, Group] = field(default_factory=dict)
    employees: dict[int, Employee] = field(default_factory=dict)
    bindings: dict[int, Binding] = field(default_factory=dict)
    messages: dict[int, Message] = field(default_factory=dict)
    attendance: dict[tuple[int, date], Attendance] = field(default_factory=dict)


class FakeDB:
    """Общее «хранилище» для всех FakeUnitOfWork одного теста плюс точки внедрения сбоев."""

    def __init__(self) -> None:
        self.state = State()
        self._ids = itertools.count(1)
        self.commits = 0
        # Сбои: сколько ближайших вызовов add_if_absent для messages упадут;
        # для каких messages.id упадёт постановка отметки; упадёт ли загрузка групп.
        self.fail_ingests = 0
        self.fail_attendance_for: set[int] = set()
        self.fail_groups_list = False

    def next_id(self) -> int:
        return next(self._ids)

    def uow(self) -> "FakeUnitOfWork":
        return FakeUnitOfWork(self)

    # Хелперы для подготовки данных в тестах (сразу «закоммичено»).
    def add_group(self, group: Group) -> Group:
        self.state.groups[group.chat_id] = group
        return group

    def add_employee(self, full_name: str, surname_norm: str, active: bool = True) -> Employee:
        employee = Employee(self.next_id(), full_name, surname_norm, active)
        self.state.employees[employee.id] = employee
        return employee

    def bind(self, tg_user_id: int, employee_id: int) -> None:
        self.state.bindings[tg_user_id] = Binding(tg_user_id, employee_id)


class FakeMessageRepository:
    def __init__(self, db: FakeDB, state: State) -> None:
        self._db, self._state = db, state

    async def add_if_absent(self, message: Message) -> bool:
        if self._db.fail_ingests > 0:
            self._db.fail_ingests -= 1
            raise ConnectionError("database is unavailable")
        if any(
            (m.chat_id, m.message_id) == (message.chat_id, message.message_id)
            for m in self._state.messages.values()
        ):
            return False
        stored = replace(message, id=self._db.next_id(), status=MessageStatus.NEW,
                         created_at=datetime.now(UTC))
        self._state.messages[stored.id] = stored
        return True

    async def take_new_batch(self, limit: int) -> list[Message]:
        new = sorted(
            (m for m in self._state.messages.values() if m.status is MessageStatus.NEW),
            key=lambda m: m.id,
        )
        return [copy.copy(m) for m in new[:limit]]

    async def get_for_update(self, id: int) -> Message:
        if id not in self._state.messages:
            raise NotFound(f"сообщение {id} не найдено")
        return copy.copy(self._state.messages[id])

    async def save_result(self, message: Message) -> None:
        self._state.messages[message.id] = copy.copy(message)

    async def list(self, status: MessageStatus | None, limit: int, offset: int) -> list[Message]:
        items = sorted(self._state.messages.values(), key=lambda m: m.id, reverse=True)
        if status is not None:
            items = [m for m in items if m.status is status]
        return [copy.copy(m) for m in items[offset : offset + limit]]


class FakeAttendanceRepository:
    def __init__(self, db: FakeDB, state: State) -> None:
        self._db, self._state = db, state

    async def add_if_absent(self, attendance: Attendance) -> bool:
        # Сначала пишем, потом падаем — чтобы проверить, что savepoint откатывает частичную запись.
        key = (attendance.employee_id, attendance.shift_date)
        if key in self._state.attendance:
            return False
        self._state.attendance[key] = replace(attendance, id=self._db.next_id())
        if attendance.message_id in self._db.fail_attendance_for:
            raise RuntimeError("boom")
        return True

    async def list_between(self, start: date, end: date, chat_id: int | None) -> list[Attendance]:
        result = [a for a in self._state.attendance.values() if start <= a.shift_date <= end]
        if chat_id is not None:
            result = [a for a in result if self._state.messages[a.message_id].chat_id == chat_id]
        return sorted(result, key=lambda a: (a.shift_date, a.employee_id))


class FakeEmployeeRepository:
    def __init__(self, db: FakeDB, state: State) -> None:
        self._db, self._state = db, state

    async def add(self, employee: Employee) -> Employee:
        stored = replace(employee, id=self._db.next_id())
        self._state.employees[stored.id] = stored
        return stored

    async def get(self, id: int) -> Employee:
        if id not in self._state.employees:
            raise NotFound(f"сотрудник {id} не найден")
        return self._state.employees[id]

    async def list(self) -> list[Employee]:
        return sorted(self._state.employees.values(), key=lambda e: e.id)


class FakeGroupRepository:
    def __init__(self, db: FakeDB, state: State) -> None:
        self._db, self._state = db, state

    async def upsert(self, group: Group) -> Group:
        self._state.groups[group.chat_id] = group
        return group

    async def list(self) -> list[Group]:
        if self._db.fail_groups_list:
            raise ConnectionError("connection lost")
        return sorted(self._state.groups.values(), key=lambda g: g.chat_id)


class FakeBindingRepository:
    def __init__(self, db: FakeDB, state: State) -> None:
        self._state = state

    async def set(self, binding: Binding) -> Binding:
        self._state.bindings[binding.tg_user_id] = binding
        return binding

    async def list(self) -> list[Binding]:
        return list(self._state.bindings.values())


class FakeUnitOfWork:
    def __init__(self, db: FakeDB) -> None:
        self._db = db

    async def __aenter__(self) -> Self:
        # Работаем с копией состояния; commit() публикует её в FakeDB.
        self._state = copy.deepcopy(self._db.state)
        self._bind_repositories()
        return self

    async def __aexit__(self, *exc_info) -> None:
        self._state = None

    def _bind_repositories(self) -> None:
        self.messages = FakeMessageRepository(self._db, self._state)
        self.attendance = FakeAttendanceRepository(self._db, self._state)
        self.employees = FakeEmployeeRepository(self._db, self._state)
        self.groups = FakeGroupRepository(self._db, self._state)
        self.bindings = FakeBindingRepository(self._db, self._state)

    async def commit(self) -> None:
        self._db.state = copy.deepcopy(self._state)
        self._db.commits += 1

    async def rollback(self) -> None:
        self._state.__dict__.update(copy.deepcopy(self._db.state).__dict__)

    @asynccontextmanager
    async def savepoint(self) -> AsyncIterator[None]:
        snapshot = copy.deepcopy(self._state)
        try:
            yield
        except BaseException:
            self._state.__dict__.update(snapshot.__dict__)
            raise
