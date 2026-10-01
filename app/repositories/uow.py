from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import TracebackType
from typing import Self

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.repositories.attendance import SqlAttendanceRepository
from app.repositories.directory import (
    SqlBindingRepository,
    SqlEmployeeRepository,
    SqlGroupRepository,
)
from app.repositories.messages import SqlMessageRepository


class SqlAlchemyUnitOfWork:
    """Одна сессия = одна транзакция. Без commit() изменения откатываются при выходе."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def __aenter__(self) -> Self:
        self._session = self._session_factory()
        self.messages = SqlMessageRepository(self._session)
        self.attendance = SqlAttendanceRepository(self._session)
        self.employees = SqlEmployeeRepository(self._session)
        self.groups = SqlGroupRepository(self._session)
        self.bindings = SqlBindingRepository(self._session)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        # close() откатывает незафиксированную транзакцию и возвращает соединение в пул.
        await self._session.close()

    async def commit(self) -> None:
        await self._session.commit()

    async def rollback(self) -> None:
        await self._session.rollback()

    @asynccontextmanager
    async def savepoint(self) -> AsyncIterator[None]:
        """Вложенная транзакция: при исключении откатывается только она, внешняя остаётся рабочей."""
        async with self._session.begin_nested():
            yield
