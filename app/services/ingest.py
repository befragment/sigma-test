import asyncio
import logging
from collections.abc import Sequence

from app.domain.models import Message
from app.domain.ports import UnitOfWorkFactory

logger = logging.getLogger(__name__)

# Telegram считает апдейт доставленным ещё до обработки, поэтому при недоступной БД сохранение
# повторяется с нарастающей паузой (суммарно ~2 минуты), а не теряется сразу.
DEFAULT_RETRY_DELAYS: Sequence[float] = (0.5, 1, 2, 5, 10, 30, 60)


class IngestService:
    """Приём сообщения с фото: только сохранить в очередь со статусом new, без вычислений."""

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        retry_delays: Sequence[float] = DEFAULT_RETRY_DELAYS,
    ) -> None:
        self._uow_factory = uow_factory
        self._retry_delays = retry_delays

    async def ingest(self, message: Message) -> bool:
        """True — сообщение новое; False — уже было принято (повторная доставка или второй бот в группе)."""
        for delay in self._retry_delays:
            try:
                return await self._save(message)
            except Exception:  # noqa: BLE001 — сбой хранилища, пробуем ещё раз
                logger.warning("ingest failed, retry in %.1fs: %r", delay, message, exc_info=True)
                await asyncio.sleep(delay)
        try:
            return await self._save(message)
        except Exception:
            logger.error("ingest gave up, message lost: %r", message)
            raise

    async def _save(self, message: Message) -> bool:
        async with self._uow_factory() as uow:
            created = await uow.messages.add_if_absent(message)
            await uow.commit()
        return created
