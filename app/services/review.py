from datetime import date

from app.domain.models import Message, MessageStatus
from app.domain.ports import UnitOfWorkFactory


class ReviewService:
    """Журнал обработки и ручная проверка спорных сообщений."""

    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def list_messages(
        self,
        status: MessageStatus | None = None,
        limit: int = 50,
        offset: int = 0,
        employee_id: int | None = None,
        shift_date: date | None = None,
    ) -> list[Message]:
        async with self._uow_factory() as uow:
            return await uow.messages.list(
                status, limit, offset, employee_id=employee_id, shift_date=shift_date
            )
