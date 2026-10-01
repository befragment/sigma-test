from datetime import time

from app.domain.errors import ValidationError
from app.domain.models import DEFAULT_TZ, Binding, Employee, Group
from app.domain.ports import UnitOfWorkFactory
from app.domain.rules import surname_norm


class DirectoryService:
    """Справочники: группы, сотрудники, привязки Telegram-аккаунтов к сотрудникам."""

    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def upsert_group(
        self,
        chat_id: int,
        title: str,
        window_start: time,
        window_end: time,
        tz: str = DEFAULT_TZ,
        active: bool = True,
    ) -> Group:
        group = Group(chat_id, title, window_start, window_end, tz, active)
        async with self._uow_factory() as uow:
            saved = await uow.groups.upsert(group)
            await uow.commit()
        return saved

    async def list_groups(self) -> list[Group]:
        async with self._uow_factory() as uow:
            return await uow.groups.list()

    async def add_employee(self, full_name: str, surname: str | None = None) -> Employee:
        full_name = " ".join(full_name.split())
        if not full_name:
            raise ValidationError("full_name не может быть пустым")
        employee = Employee(None, full_name, surname_norm(full_name, surname))
        async with self._uow_factory() as uow:
            saved = await uow.employees.add(employee)
            await uow.commit()
        return saved

    async def list_employees(self) -> list[Employee]:
        async with self._uow_factory() as uow:
            return await uow.employees.list()

    async def bind(self, tg_user_id: int, employee_id: int) -> Binding:
        async with self._uow_factory() as uow:
            await uow.employees.get(employee_id)  # NotFound, если сотрудника нет
            binding = await uow.bindings.set(Binding(tg_user_id, employee_id))
            await uow.commit()
        return binding
