"""Справочники: группы, сотрудники, привязки Telegram-аккаунтов."""

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.errors import NotFound
from app.domain.models import Binding, Employee, Group
from app.repositories.orm import BindingRow, EmployeeRow, GroupRow


def _group(row: GroupRow) -> Group:
    return Group(
        chat_id=row.chat_id,
        title=row.title,
        tz=row.tz,
        window_start=row.window_start,
        window_end=row.window_end,
        active=row.active,
    )


def _employee(row: EmployeeRow) -> Employee:
    return Employee(
        id=row.id, full_name=row.full_name, surname_norm=row.surname_norm, active=row.active
    )


class SqlGroupRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(self, group: Group) -> Group:
        values = {
            "title": group.title,
            "tz": group.tz,
            "window_start": group.window_start,
            "window_end": group.window_end,
            "active": group.active,
        }
        stmt = (
            insert(GroupRow)
            .values(chat_id=group.chat_id, **values)
            .on_conflict_do_update(index_elements=[GroupRow.chat_id], set_=values)
            .returning(GroupRow)
            .execution_options(populate_existing=True)
        )
        return _group(await self._session.scalar(stmt))

    async def list(self) -> list[Group]:
        rows = await self._session.scalars(select(GroupRow).order_by(GroupRow.chat_id))
        return [_group(row) for row in rows]


class SqlEmployeeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, employee: Employee) -> Employee:
        row = EmployeeRow(
            full_name=employee.full_name,
            surname_norm=employee.surname_norm,
            active=employee.active,
        )
        self._session.add(row)
        await self._session.flush()
        return _employee(row)

    async def get(self, id: int) -> Employee:
        row = await self._session.get(EmployeeRow, id)
        if row is None:
            raise NotFound(f"сотрудник {id} не найден")
        return _employee(row)

    async def list(self) -> list[Employee]:
        rows = await self._session.scalars(select(EmployeeRow).order_by(EmployeeRow.id))
        return [_employee(row) for row in rows]


class SqlBindingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def set(self, binding: Binding) -> Binding:
        stmt = (
            insert(BindingRow)
            .values(tg_user_id=binding.tg_user_id, employee_id=binding.employee_id)
            .on_conflict_do_update(
                index_elements=[BindingRow.tg_user_id],
                set_={"employee_id": binding.employee_id},
            )
        )
        await self._session.execute(stmt)
        return binding

    async def list(self) -> list[Binding]:
        rows = await self._session.scalars(select(BindingRow))
        return [Binding(tg_user_id=row.tg_user_id, employee_id=row.employee_id) for row in rows]
