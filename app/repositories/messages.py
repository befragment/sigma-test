from datetime import date

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.errors import NotFound
from app.domain.models import Message, MessageStatus
from app.repositories.orm import MessageRow


def _to_domain(row: MessageRow) -> Message:
    return Message(
        id=row.id,
        chat_id=row.chat_id,
        message_id=row.message_id,
        tg_user_id=row.tg_user_id,
        media_group_id=row.media_group_id,
        caption=row.caption,
        sent_at=row.sent_at,
        status=MessageStatus(row.status),
        reason=row.reason,
        employee_id=row.employee_id,
        shift_date=row.shift_date,
        created_at=row.created_at,
        processed_at=row.processed_at,
    )


class SqlMessageRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_if_absent(self, message: Message) -> bool:
        stmt = (
            insert(MessageRow)
            .values(
                chat_id=message.chat_id,
                message_id=message.message_id,
                tg_user_id=message.tg_user_id,
                media_group_id=message.media_group_id,
                caption=message.caption,
                sent_at=message.sent_at,
                status=MessageStatus.NEW.value,
            )
            .on_conflict_do_nothing(index_elements=[MessageRow.chat_id, MessageRow.message_id])
            .returning(MessageRow.id)
        )
        return (await self._session.scalar(stmt)) is not None

    async def take_new_batch(self, limit: int) -> list[Message]:
        stmt = (
            select(MessageRow)
            .where(MessageRow.status == MessageStatus.NEW.value)
            .order_by(MessageRow.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return [_to_domain(row) for row in await self._session.scalars(stmt)]

    async def get_for_update(self, id: int) -> Message:
        row = await self._session.scalar(
            select(MessageRow)
            .where(MessageRow.id == id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if row is None:
            raise NotFound(f"сообщение {id} не найдено")
        return _to_domain(row)

    async def save_result(self, message: Message) -> None:
        await self._session.execute(
            update(MessageRow)
            .where(MessageRow.id == message.id)
            .values(
                status=message.status.value,
                reason=message.reason,
                employee_id=message.employee_id,
                shift_date=message.shift_date,
                processed_at=message.processed_at,
            )
        )

    async def list(
        self,
        status: MessageStatus | None,
        limit: int,
        offset: int,
        employee_id: int | None = None,
        shift_date: date | None = None,
    ) -> list[Message]:
        stmt = select(MessageRow).order_by(MessageRow.id.desc()).limit(limit).offset(offset)
        if status is not None:
            stmt = stmt.where(MessageRow.status == status.value)
        if employee_id is not None:
            stmt = stmt.where(MessageRow.employee_id == employee_id)
        if shift_date is not None:
            stmt = stmt.where(MessageRow.shift_date == shift_date)
        return [_to_domain(row) for row in await self._session.scalars(stmt)]
