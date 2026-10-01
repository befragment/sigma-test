from datetime import date

import pytest

from app.domain.errors import ValidationError
from app.domain.models import Attendance, Employee
from app.domain.rules import build_timesheet, month_bounds, parse_month

PETROV = Employee(1, "Петров Сергей", "петров")
ELKIN = Employee(2, "Ёлкин Олег", "елкин")
ANTONOV = Employee(3, "Антонов Иван", "антонов")
FIRED = Employee(4, "Сидоров Павел", "сидоров", active=False)
FIRED_NO_MARKS = Employee(5, "Уволенный Без Отметок", "уволенный", active=False)
EMPLOYEES = [PETROV, ELKIN, ANTONOV, FIRED, FIRED_NO_MARKS]


def mark(employee: Employee, day: date) -> Attendance:
    return Attendance(employee.id, day, message_id=100)


class TestMonth:
    def test_parse(self):
        assert parse_month("2025-09") == (2025, 9)

    @pytest.mark.parametrize("value", ["2025-13", "2025-00", "2025-9", "09-2025", "2025-09-01", ""])
    def test_invalid(self, value):
        with pytest.raises(ValidationError):
            parse_month(value)

    @pytest.mark.parametrize(
        ("year", "month", "last"),
        [(2025, 9, 30), (2025, 2, 28), (2024, 2, 29), (2025, 12, 31)],
    )
    def test_bounds(self, year, month, last):
        assert month_bounds(year, month) == (date(year, month, 1), date(year, month, last))


class TestBuildTimesheet:
    def test_all_active_plus_marked_inactive_sorted_by_name(self):
        marks = [mark(PETROV, date(2025, 9, 19)), mark(PETROV, date(2025, 9, 20)),
                 mark(FIRED, date(2025, 9, 1))]

        sheet = build_timesheet(2025, 9, EMPLOYEES, marks, only_marked=False)

        assert [(r.full_name, sorted(r.days)) for r in sheet.rows] == [
            ("Антонов Иван", []),
            ("Ёлкин Олег", []),  # «ё» сортируется как «е», а не в конец алфавита
            ("Петров Сергей", [19, 20]),
            ("Сидоров Павел", [1]),
        ]
        assert sheet.title == "Табель за сентябрь 2025"
        assert sheet.days_in_month == 30

    def test_only_marked_for_group(self):
        sheet = build_timesheet(2025, 9, EMPLOYEES, [mark(ELKIN, date(2025, 9, 5))],
                                only_marked=True, group_title="Пост 1")

        assert [(r.full_name, set(r.days)) for r in sheet.rows] == [("Ёлкин Олег", {5})]
        assert sheet.title == "Табель за сентябрь 2025 — Пост 1"

    def test_marks_of_other_months_ignored(self):
        sheet = build_timesheet(2025, 9, [PETROV], [mark(PETROV, date(2025, 10, 1))], only_marked=True)
        assert sheet.rows == ()

    def test_february_leap_year(self):
        assert build_timesheet(2024, 2, [], [], only_marked=False).days_in_month == 29
