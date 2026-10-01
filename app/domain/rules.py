import calendar
import re
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.domain.errors import ValidationError
from app.domain.models import (
    Attendance,
    Decision,
    Employee,
    EmployeeIndex,
    Group,
    Message,
    MessageStatus,
    Reason,
    Timesheet,
    TimesheetRow,
)

# Слово — буквы, допускается дефис внутри (двойные фамилии). Цифры, эмодзи и пунктуация отбрасываются.
_WORD_RE = re.compile(r"[^\W\d_]+(?:-[^\W\d_]+)*")


def normalize_word(word: str) -> str:
    return word.lower().replace("ё", "е")


def caption_words(caption: str | None) -> list[str]:
    if not caption:
        return []
    return [normalize_word(word) for word in _WORD_RE.findall(caption)]


def surname_norm(full_name: str, surname: str | None = None) -> str:
    """Нормализованная фамилия: явно заданная или первое слово ФИО."""
    words = caption_words(surname or full_name)
    if not words:
        raise ValidationError("не удалось выделить фамилию")
    return words[0]


def shift_date(sent_at: datetime, group: Group) -> date | None:
    """Дата смены по окну группы или None, если сообщение вне окна.

    Время переводится в таймзону группы и сравнивается с точностью до минуты, обе границы включительно.
    Окно через полночь (start > end): после start — смена текущей даты, до end — смена предыдущей.
    """
    if sent_at.tzinfo is None:
        sent_at = sent_at.replace(tzinfo=UTC)
    local = sent_at.astimezone(ZoneInfo(group.tz))
    moment = local.time().replace(second=0, microsecond=0)
    start, end = group.window_start, group.window_end

    if not group.crosses_midnight:
        return local.date() if start <= moment <= end else None
    if moment >= start:
        return local.date()
    if moment <= end:
        return local.date() - timedelta(days=1)
    return None


def message_link(chat_id: int, message_id: int) -> str | None:
    """Ссылка на сообщение. Есть только у супергрупп (chat_id вида -100...)."""
    raw = str(chat_id)
    if not raw.startswith("-100"):
        return None
    return f"https://t.me/c/{raw[4:]}/{message_id}"


def decide(
    message: Message,
    group: Group | None,
    employees: EmployeeIndex,
    bound_employee_id: int | None,
) -> Decision:
    """Решение по сообщению с фото. Чистая функция: всё нужное передаётся аргументами.

    bound_employee_id — сотрудник, к которому привязан Telegram-аккаунт автора; привязка к неактивному
    сотруднику не учитывается.
    """
    if group is None or not group.active:
        return Decision(MessageStatus.REJECTED, Reason.UNKNOWN_GROUP)

    day = shift_date(message.sent_at, group)
    if day is None:
        return Decision(MessageStatus.REJECTED, Reason.OUTSIDE_WINDOW)

    def accepted(reason: Reason, employee_id: int) -> Decision:
        return Decision(MessageStatus.ACCEPTED, reason, employee_id, day)

    def review(reason: Reason) -> Decision:
        return Decision(MessageStatus.MANUAL_REVIEW, reason, None, day)

    bound = bound_employee_id if bound_employee_id in employees.active_ids else None
    surnames = {word for word in caption_words(message.caption) if word in employees.by_surname}

    if len(surnames) >= 2:
        return review(Reason.MULTIPLE_EMPLOYEES)

    if len(surnames) == 1:
        candidates = employees.by_surname[surnames.pop()]
        if len(candidates) > 1:
            if bound in candidates:
                return accepted(Reason.BY_CAPTION_AND_ACCOUNT, bound)
            return review(Reason.AMBIGUOUS_SURNAME)
        (candidate,) = candidates
        if bound is None:
            return accepted(Reason.BY_CAPTION, candidate)
        if bound == candidate:
            return accepted(Reason.BY_CAPTION_AND_ACCOUNT, candidate)
        return review(Reason.CAPTION_ACCOUNT_MISMATCH)

    if bound is not None:
        return accepted(Reason.BY_ACCOUNT, bound)

    if message.caption and message.caption.strip():
        return review(Reason.EMPLOYEE_NOT_FOUND)
    if message.media_group_id:
        return Decision(MessageStatus.REJECTED, Reason.ALBUM_PART_WITHOUT_CAPTION, None, day)
    return review(Reason.NO_CAPTION)


_MONTH_RE = re.compile(r"(\d{4})-(\d{2})")
_MONTH_NAMES = (
    "январь", "февраль", "март", "апрель", "май", "июнь",
    "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь",
)


def parse_month(value: str) -> tuple[int, int]:
    """«YYYY-MM» → (год, месяц)."""
    match = _MONTH_RE.fullmatch(value)
    if not match or not 1 <= int(match.group(2)) <= 12:
        raise ValidationError(f"месяц должен быть в формате YYYY-MM: {value!r}")
    return int(match.group(1)), int(match.group(2))


def month_bounds(year: int, month: int) -> tuple[date, date]:
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def build_timesheet(
    year: int,
    month: int,
    employees: Iterable[Employee],
    marks: Iterable[Attendance],
    *,
    only_marked: bool,
    group_title: str | None = None,
) -> Timesheet:
    """Строки табеля за месяц, по алфавиту ФИО.

    only_marked=False — все активные сотрудники плюс те, у кого есть отметки (в т.ч. уже неактивные);
    only_marked=True — только сотрудники с отметками (табель по одной группе).
    """
    days: dict[int, set[int]] = {}
    for mark in marks:
        if (mark.shift_date.year, mark.shift_date.month) == (year, month):
            days.setdefault(mark.employee_id, set()).add(mark.shift_date.day)

    rows = [
        TimesheetRow(employee.full_name, frozenset(days.get(employee.id, ())))
        for employee in employees
        if employee.id in days or (employee.active and not only_marked)
    ]
    rows.sort(key=lambda row: normalize_word(row.full_name))

    title = f"Табель за {_MONTH_NAMES[month - 1]} {year}"
    if group_title:
        title += f" — {group_title}"
    return Timesheet(year, month, title, tuple(rows))
