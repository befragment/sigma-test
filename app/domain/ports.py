"""Интерфейсы хранилища, от которых зависят сервисы. Реализации — в app.repositories."""

from datetime import date
from types import TracebackType
from typing import Protocol, Self

from app.domain.models import Attendance, Binding, Employee, Group, Message, MessageStatus


class MessageRepository(Protocol):
    async def add_if_absent(self, message: Message) -> bool:
        """Сохранить новое сообщение; False, если (chat_id, message_id) уже есть."""

    async def take_new_batch(self, limit: int) -> list[Message]:
        """Забрать пачку new с блокировкой строк до конца транзакции (FOR UPDATE SKIP LOCKED)."""

    async def get_for_update(self, id: int) -> Message:
        """Сообщение по id с блокировкой строки; NotFound, если нет."""

    async def save_result(self, message: Message) -> None:
        """Сохранить итог обработки: status, reason, employee_id, shift_date, processed_at."""

    async def list(
        self, status: MessageStatus | None, limit: int, offset: int
    ) -> list[Message]: ...


class AttendanceRepository(Protocol):
    async def add_if_absent(self, attendance: Attendance) -> bool:
        """Поставить отметку; False, если у сотрудника уже есть отметка на эту дату."""

    async def list_between(
        self, start: date, end: date, chat_id: int | None
    ) -> list[Attendance]: ...


class EmployeeRepository(Protocol):
    async def add(self, employee: Employee) -> Employee: ...

    async def get(self, id: int) -> Employee:
        """NotFound, если нет."""

    async def list(self) -> list[Employee]: ...


class GroupRepository(Protocol):
    async def upsert(self, group: Group) -> Group: ...

    async def list(self) -> list[Group]: ...


class BindingRepository(Protocol):
    async def set(self, binding: Binding) -> Binding: ...

    async def list(self) -> list[Binding]: ...


class UnitOfWork(Protocol):
    """Одна транзакция. Без commit() изменения откатываются при выходе из контекста."""

    messages: MessageRepository
    attendance: AttendanceRepository
    employees: EmployeeRepository
    groups: GroupRepository
    bindings: BindingRepository

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


class UnitOfWorkFactory(Protocol):
    def __call__(self) -> UnitOfWork: ...

