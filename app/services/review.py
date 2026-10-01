from collections.abc import Callable
from datetime import UTC, date, datetime

from app.domain.errors import InvalidState, ValidationError
from app.domain.models import Attendance, Message, MessageStatus, Reason
from app.domain.ports import UnitOfWork, UnitOfWorkFactory


class ReviewService:
    """Журнал обработки и ручная проверка спорных сообщений."""

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

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

    async def list_review(self, limit: int = 50, offset: int = 0) -> list[Message]:
        return await self.list_messages(MessageStatus.MANUAL_REVIEW, limit, offset)

    async def approve(
        self, id: int, employee_id: int, shift_date: date | None = None
    ) -> Message:
        """Подтвердить спорное сообщение: отметка с manual=true; если отметка уже есть — duplicate."""
        async with self._uow_factory() as uow:
            message = await self._take_for_review(uow, id)
            employee = await uow.employees.get(employee_id)
            if not employee.active:
                raise ValidationError(f"сотрудник {employee_id} неактивен")
            day = shift_date or message.shift_date
            if day is None:
                raise ValidationError("shift_date обязателен: у сообщения нет рассчитанной даты смены")

            created = await uow.attendance.add_if_absent(
                Attendance(employee_id=employee_id, shift_date=day, message_id=message.id, manual=True)
            )
            if created:
                message.status, message.reason = MessageStatus.ACCEPTED, Reason.MANUAL_APPROVED.value
            else:
                message.status, message.reason = MessageStatus.DUPLICATE, Reason.ALREADY_MARKED.value
            message.employee_id = employee_id
            message.shift_date = day
            message.processed_at = self._clock()
            await uow.messages.save_result(message)
            await uow.commit()
        return message

    async def reject(self, id: int) -> Message:
        async with self._uow_factory() as uow:
            message = await self._take_for_review(uow, id)
            message.status = MessageStatus.REJECTED
            message.reason = Reason.MANUAL_REJECTED.value
            message.processed_at = self._clock()
            await uow.messages.save_result(message)
            await uow.commit()
        return message

    async def _take_for_review(self, uow: UnitOfWork, id: int) -> Message:
        # Блокировка строки: два оператора не смогут одновременно решить одно сообщение.
        message = await uow.messages.get_for_update(id)
        if message.status is not MessageStatus.MANUAL_REVIEW:
            raise InvalidState(
                f"сообщение {id} в статусе {message.status.value}, ожидается manual_review"
            )
        return message
