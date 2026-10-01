import logging
from collections.abc import Callable
from datetime import UTC, datetime

from app.domain.models import Attendance, Decision, EmployeeIndex, Message, MessageStatus, Reason
from app.domain.ports import UnitOfWork, UnitOfWorkFactory
from app.domain.rules import decide

logger = logging.getLogger(__name__)

MAX_REASON = 1000


class ProcessingService:
    """Обработка очереди: пачка new → решение → отметка в табеле и итоговый статус в одной транзакции."""

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        batch_size: int,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._uow_factory = uow_factory
        self._batch_size = batch_size
        self._clock = clock

    async def process_batch(self) -> int:
        """Обработать одну пачку; возвращает число обработанных сообщений (0 — очередь пуста)."""
        async with self._uow_factory() as uow:
            messages = await uow.messages.take_new_batch(self._batch_size)
            if not messages:
                return 0

            groups = {group.chat_id: group for group in await uow.groups.list()}
            bindings = {b.tg_user_id: b.employee_id for b in await uow.bindings.list()}
            employees = EmployeeIndex.build(await uow.employees.list())

            for message in messages:
                try:
                    async with uow.savepoint():
                        bound = bindings.get(message.tg_user_id)
                        decision = decide(message, groups.get(message.chat_id), employees, bound)
                        await self._apply(uow, message, decision)
                except Exception as exc:  # noqa: BLE001 — ошибка одного сообщения не роняет пачку
                    logger.exception("failed to process message id=%s", message.id)
                    await self._fail(uow, message, exc)

            await uow.commit()
        logger.info("processed %d messages", len(messages))
        return len(messages)

    async def _apply(self, uow: UnitOfWork, message: Message, decision: Decision) -> None:
        status, reason = decision.status, decision.reason
        if status is MessageStatus.ACCEPTED:
            created = await uow.attendance.add_if_absent(
                Attendance(
                    employee_id=decision.employee_id,
                    shift_date=decision.shift_date,
                    message_id=message.id,
                )
            )
            if not created:
                status, reason = MessageStatus.DUPLICATE, Reason.ALREADY_MARKED

        message.status = status
        message.reason = reason.value
        message.employee_id = decision.employee_id
        message.shift_date = decision.shift_date
        message.processed_at = self._clock()
        await uow.messages.save_result(message)

    async def _fail(self, uow: UnitOfWork, message: Message, exc: Exception) -> None:
        message.status = MessageStatus.ERROR
        message.reason = f"{Reason.PROCESSING_ERROR.value}: {type(exc).__name__}: {exc}"[:MAX_REASON]
        message.employee_id = None
        message.shift_date = None
        message.processed_at = self._clock()
        await uow.messages.save_result(message)
