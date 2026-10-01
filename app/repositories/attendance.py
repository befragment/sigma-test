from datetime import date

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import Attendance
from app.repositories.orm import AttendanceRow, MessageRow


def _to_domain(row: AttendanceRow) -> Attendance:
    return Attendance(
        id=row.id,
        employee_id=row.employee_id,
        shift_date=row.shift_date,
        message_id=row.message_id,
        manual=row.manual,
        created_at=row.created_at,
    )


class SqlAttendanceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_if_absent(self, attendance: Attendance) -> bool:
        stmt = (
            insert(AttendanceRow)
            .values(
                employee_id=attendance.employee_id,
                shift_date=attendance.shift_date,
                message_id=attendance.message_id,
                manual=attendance.manual,
            )
            .on_conflict_do_nothing(
                index_elements=[AttendanceRow.employee_id, AttendanceRow.shift_date]
            )
            .returning(AttendanceRow.id)
        )
        return (await self._session.scalar(stmt)) is not None

    async def list_between(
        self, start: date, end: date, chat_id: int | None
    ) -> list[Attendance]:
        stmt = (
            select(AttendanceRow)
            .where(AttendanceRow.shift_date.between(start, end))
            .order_by(AttendanceRow.shift_date, AttendanceRow.employee_id)
        )
        if chat_id is not None:
            stmt = stmt.join(MessageRow, MessageRow.id == AttendanceRow.message_id).where(
                MessageRow.chat_id == chat_id
            )
        return [_to_domain(row) for row in await self._session.scalars(stmt)]
