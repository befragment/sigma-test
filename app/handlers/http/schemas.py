from datetime import date, datetime, time

from pydantic import BaseModel, ConfigDict, Field

from app.domain.models import DEFAULT_TZ, Message, MessageStatus
from app.domain.rules import message_link


class GroupIn(BaseModel):
    chat_id: int
    title: str = Field(min_length=1, max_length=255)
    window_start: time = Field(description="Начало окна отметки, местное время группы")
    window_end: time = Field(description="Конец окна; если раньше начала — окно через полночь")
    tz: str = DEFAULT_TZ
    active: bool = True


class GroupOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    chat_id: int
    title: str
    window_start: time
    window_end: time
    tz: str
    active: bool


class EmployeeIn(BaseModel):
    full_name: str = Field(min_length=1, max_length=255)
    surname: str | None = Field(
        default=None, max_length=255, description="Если не задана — первое слово ФИО"
    )


class EmployeeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    full_name: str
    surname_norm: str
    active: bool


class BindingIn(BaseModel):
    employee_id: int


class BindingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    tg_user_id: int
    employee_id: int


class ApproveIn(BaseModel):
    employee_id: int
    shift_date: date | None = Field(
        default=None, description="Если не задана — рассчитанная по окну группы дата смены"
    )


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    chat_id: int
    message_id: int
    tg_user_id: int | None
    media_group_id: str | None
    caption: str | None
    sent_at: datetime
    status: MessageStatus
    reason: str | None
    employee_id: int | None
    shift_date: date | None
    created_at: datetime | None
    processed_at: datetime | None
    link: str | None = Field(description="Ссылка на первоисточник (только для супергрупп)")

    @classmethod
    def from_domain(cls, message: Message) -> "MessageOut":
        return cls.model_validate(
            {**message.__dict__, "link": message_link(message.chat_id, message.message_id)}
        )
