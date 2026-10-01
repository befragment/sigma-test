import asyncio
import logging

from app.services.processing import ProcessingService

logger = logging.getLogger(__name__)


async def run_worker(service: ProcessingService, poll_interval: float) -> None:
    """Цикл воркера: обрабатывать пачки подряд, пока есть работа; при пустой очереди или сбое — пауза.

    При сбое транзакция пачки откатывается, сообщения остаются new и будут взяты повторно.
    """
    while True:
        try:
            processed = await service.process_batch()
        except Exception:  # noqa: BLE001 — воркер не должен умирать от сбоя одной пачки
            logger.exception("batch processing failed")
            processed = 0
        if processed == 0:
            await asyncio.sleep(poll_interval)
