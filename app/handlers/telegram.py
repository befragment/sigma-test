from aiogram import Dispatcher, F, Router
from aiogram.enums import ChatType
from aiogram.types import Message as TgMessage

from app.domain.models import Message
from app.services.ingest import IngestService


def create_dispatcher(ingest: IngestService) -> Dispatcher:
    """Один Dispatcher на все боты; реагирует только на фото в группах и супергруппах."""
    router = Router(name="photos")

    @router.message(F.photo, F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}))
    async def on_photo(message: TgMessage) -> None:
        await ingest.ingest(
            Message(
                chat_id=message.chat.id,
                message_id=message.message_id,
                sent_at=message.date,
                tg_user_id=message.from_user.id if message.from_user else None,
                media_group_id=message.media_group_id,
                caption=message.caption,
            )
        )

    dispatcher = Dispatcher()
    dispatcher.include_router(router)
    return dispatcher
