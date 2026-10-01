from datetime import UTC, datetime

import pytest

from app.domain.models import Message, MessageStatus
from app.services.ingest import IngestService
from tests.fakes import FakeDB


def photo(message_id: int = 1) -> Message:
    return Message(
        chat_id=-1001,
        message_id=message_id,
        sent_at=datetime(2025, 9, 19, 5, 50, tzinfo=UTC),
        tg_user_id=777,
        caption="Мехоношин",
    )


async def test_new_message_saved_as_new():
    db = FakeDB()

    assert await IngestService(db.uow).ingest(photo()) is True

    [message] = db.state.messages.values()
    assert (message.chat_id, message.message_id, message.caption) == (-1001, 1, "Мехоношин")
    assert message.status is MessageStatus.NEW


async def test_repeated_delivery_is_ignored():
    db = FakeDB()
    service = IngestService(db.uow)

    assert await service.ingest(photo()) is True
    assert await service.ingest(photo()) is False
    assert await service.ingest(photo(message_id=2)) is True
    assert len(db.state.messages) == 2


async def test_retries_until_storage_is_back():
    db = FakeDB()
    db.fail_ingests = 2

    assert await IngestService(db.uow, retry_delays=(0, 0, 0)).ingest(photo()) is True
    assert len(db.state.messages) == 1


async def test_gives_up_after_all_retries():
    db = FakeDB()
    db.fail_ingests = 4  # 3 попытки по паузам + последняя

    with pytest.raises(ConnectionError):
        await IngestService(db.uow, retry_delays=(0, 0, 0)).ingest(photo())
    assert db.state.messages == {}
