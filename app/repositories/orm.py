from datetime import date, datetime, time

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    Time,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.domain.models import DEFAULT_TZ, MessageStatus


class Base(DeclarativeBase):
    pass


class GroupRow(Base):
    __tablename__ = "tg_groups"

    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    title: Mapped[str] = mapped_column(String(255))
    tz: Mapped[str] = mapped_column(String(64), server_default=DEFAULT_TZ)
    window_start: Mapped[time] = mapped_column(Time)
    window_end: Mapped[time] = mapped_column(Time)
    active: Mapped[bool] = mapped_column(server_default=text("true"))


class EmployeeRow(Base):
    __tablename__ = "employees"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    full_name: Mapped[str] = mapped_column(String(255))
    surname_norm: Mapped[str] = mapped_column(String(255), index=True)
    active: Mapped[bool] = mapped_column(server_default=text("true"))


class BindingRow(Base):
    __tablename__ = "telegram_bindings"

    tg_user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"))


class MessageRow(Base):
    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint("chat_id", "message_id", name="uq_messages_chat_message"),
        # Очередь: воркеры выбирают new по возрастанию id.
        Index("ix_messages_new", "id", postgresql_where=text("status = 'new'")),
        # Журнал и список на ручную проверку.
        Index("ix_messages_status_id", "status", "id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    chat_id: Mapped[int] = mapped_column(BigInteger)
    message_id: Mapped[int] = mapped_column(BigInteger)
    tg_user_id: Mapped[int | None] = mapped_column(BigInteger)
    media_group_id: Mapped[str | None] = mapped_column(String(64))
    caption: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32), server_default=MessageStatus.NEW.value)
    reason: Mapped[str | None] = mapped_column(Text)
    employee_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id"))
    shift_date: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AttendanceRow(Base):
    __tablename__ = "attendance"
    __table_args__ = (
        UniqueConstraint("employee_id", "shift_date", name="uq_attendance_employee_date"),
        Index("ix_attendance_shift_date", "shift_date"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"))
    shift_date: Mapped[date] = mapped_column(Date)
    message_id: Mapped[int] = mapped_column(ForeignKey("messages.id"))
    manual: Mapped[bool] = mapped_column(server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


async def create_schema(engine: AsyncEngine) -> None:
    """Упрощение первой версии: схема создаётся при старте вместо миграций."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
