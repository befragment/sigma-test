from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, time
from enum import StrEnum
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.domain.errors import ValidationError

DEFAULT_TZ = "Europe/Moscow"


class MessageStatus(StrEnum):
    NEW = "new"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    MANUAL_REVIEW = "manual_review"
    DUPLICATE = "duplicate"
    ERROR = "error"


class Reason(StrEnum):
    # rejected
    UNKNOWN_GROUP = "unknown_group"
    OUTSIDE_WINDOW = "outside_window"
    ALBUM_PART_WITHOUT_CAPTION = "album_part_without_caption"
    MANUAL_REJECTED = "manual_rejected"
    # manual_review
    MULTIPLE_EMPLOYEES = "multiple_employees"
    AMBIGUOUS_SURNAME = "ambiguous_surname"
    CAPTION_ACCOUNT_MISMATCH = "caption_account_mismatch"
    NO_CAPTION = "no_caption"
    EMPLOYEE_NOT_FOUND = "employee_not_found"
    # accepted
    BY_CAPTION = "by_caption"
    BY_CAPTION_AND_ACCOUNT = "by_caption_and_account"
    BY_ACCOUNT = "by_account"
    MANUAL_APPROVED = "manual_approved"
    # duplicate: у сотрудника уже есть отметка на эту дату
    ALREADY_MARKED = "already_marked"
    # error
    PROCESSING_ERROR = "processing_error"


@dataclass(frozen=True)
class Group:
    chat_id: int
    title: str
    window_start: time
    window_end: time
    tz: str = DEFAULT_TZ
    active: bool = True

    def __post_init__(self) -> None:
        if self.window_start == self.window_end:
            raise ValidationError("window_start и window_end не должны совпадать")
        try:
            ZoneInfo(self.tz)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValidationError(f"неизвестная таймзона: {self.tz}") from exc

    @property
    def crosses_midnight(self) -> bool:
        return self.window_start > self.window_end


@dataclass(frozen=True)
class Employee:
    id: int | None
    full_name: str
    surname_norm: str
    active: bool = True


@dataclass(frozen=True)
class Binding:
    tg_user_id: int
    employee_id: int


@dataclass
class Message:
    chat_id: int
    message_id: int
    sent_at: datetime
    tg_user_id: int | None = None
    media_group_id: str | None = None
    caption: str | None = None
    id: int | None = None
    status: MessageStatus = MessageStatus.NEW
    # Код причины (значение Reason); для ошибок обработки — с текстом исключения.
    reason: str | None = None
    employee_id: int | None = None
    shift_date: date | None = None
    created_at: datetime | None = None
    processed_at: datetime | None = None


@dataclass(frozen=True)
class Attendance:
    employee_id: int
    shift_date: date
    message_id: int
    manual: bool = False
    id: int | None = None
    created_at: datetime | None = None


@dataclass(frozen=True)
class Decision:
    status: MessageStatus
    reason: Reason
    employee_id: int | None = None
    shift_date: date | None = None


@dataclass(frozen=True)
class EmployeeIndex:
    """Справочник активных сотрудников, подготовленный для decide(): нормализованная фамилия → id."""

    by_surname: Mapping[str, tuple[int, ...]]
    active_ids: frozenset[int]

    @classmethod
    def build(cls, employees: Iterable[Employee]) -> "EmployeeIndex":
        by_surname: dict[str, list[int]] = {}
        active_ids: set[int] = set()
        for employee in employees:
            if not employee.active or employee.id is None:
                continue
            by_surname.setdefault(employee.surname_norm, []).append(employee.id)
            active_ids.add(employee.id)
        return cls(
            by_surname={surname: tuple(ids) for surname, ids in by_surname.items()},
            active_ids=frozenset(active_ids),
        )
