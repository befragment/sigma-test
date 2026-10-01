from dataclasses import replace
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pytest

from app.domain.models import Decision, Employee, EmployeeIndex, Group, Message, MessageStatus, Reason
from app.domain.rules import decide

MSK = ZoneInfo("Europe/Moscow")
SHIFT_DAY = date(2025, 9, 19)

GROUP = Group(chat_id=-1001, title="Пост 1", window_start=time(7, 0), window_end=time(10, 0))

MEKHONOSHIN, IVANOV_IVAN, IVANOV_PETR, PETROV, ELKIN, SIDOROV_FIRED = 1, 2, 3, 4, 5, 6
EMPLOYEES = EmployeeIndex.build(
    [
        Employee(MEKHONOSHIN, "Мехоношин Алексей", "мехоношин"),
        Employee(IVANOV_IVAN, "Иванов Иван", "иванов"),
        Employee(IVANOV_PETR, "Иванов Пётр", "иванов"),
        Employee(PETROV, "Петров Сергей", "петров"),
        Employee(ELKIN, "Ёлкин Олег", "елкин"),
        Employee(SIDOROV_FIRED, "Сидоров Павел", "сидоров", active=False),
    ]
)


def message(
    caption: str | None = None,
    *,
    sent_at: datetime = datetime(2025, 9, 19, 8, 50, 6, tzinfo=MSK),
    media_group_id: str | None = None,
) -> Message:
    return Message(
        chat_id=GROUP.chat_id,
        message_id=100,
        sent_at=sent_at,
        tg_user_id=777,
        media_group_id=media_group_id,
        caption=caption,
    )


def run(msg: Message, bound: int | None = None, group: Group | None = GROUP) -> Decision:
    return decide(msg, group, EMPLOYEES, bound)


def accepted(reason: Reason, employee_id: int) -> Decision:
    return Decision(MessageStatus.ACCEPTED, reason, employee_id, SHIFT_DAY)


def review(reason: Reason) -> Decision:
    return Decision(MessageStatus.MANUAL_REVIEW, reason, None, SHIFT_DAY)


def test_example_from_task():
    """Пример из ТЗ: «Мехоношин» в 08:50 по Москве → отметка в день сообщения."""
    assert run(message("Мехоношин")) == accepted(Reason.BY_CAPTION, MEKHONOSHIN)


class TestGroupAndWindow:
    def test_unknown_group(self):
        assert run(message("Мехоношин"), group=None) == Decision(
            MessageStatus.REJECTED, Reason.UNKNOWN_GROUP
        )

    def test_inactive_group(self):
        group = replace(GROUP, active=False)
        assert run(message("Мехоношин"), group=group).reason == Reason.UNKNOWN_GROUP

    def test_outside_window(self):
        msg = message("Мехоношин", sent_at=datetime(2025, 9, 19, 12, 0, tzinfo=MSK))
        assert run(msg) == Decision(MessageStatus.REJECTED, Reason.OUTSIDE_WINDOW)

    def test_window_checked_before_employee(self):
        msg = message("Мехоношин Петров", sent_at=datetime(2025, 9, 19, 12, 0, tzinfo=MSK))
        assert run(msg).reason == Reason.OUTSIDE_WINDOW

    @pytest.mark.parametrize(
        ("sent_at", "expected_day"),
        [
            (datetime(2025, 9, 18, 22, 30, tzinfo=MSK), date(2025, 9, 18)),
            (datetime(2025, 9, 19, 2, 0, tzinfo=MSK), date(2025, 9, 18)),
        ],
        ids=["before-midnight", "after-midnight"],
    )
    def test_overnight_window(self, sent_at, expected_day):
        group = replace(GROUP, window_start=time(20, 0), window_end=time(8, 0))
        decision = run(message("Мехоношин", sent_at=sent_at), group=group)
        assert decision == Decision(
            MessageStatus.ACCEPTED, Reason.BY_CAPTION, MEKHONOSHIN, expected_day
        )


class TestEmployeeByCaption:
    @pytest.mark.parametrize(
        "caption",
        ["Мехоношин", "мехоношин", "МЕХОНОШИН.", "Мехоношин заступил на смену 🚀", "Пост 3, Мехоношин"],
    )
    def test_surname_found(self, caption):
        assert run(message(caption)) == accepted(Reason.BY_CAPTION, MEKHONOSHIN)

    def test_yo_normalized(self):
        assert run(message("ЁЛКИН на посту")) == accepted(Reason.BY_CAPTION, ELKIN)

    def test_same_surname_twice_is_one_employee(self):
        assert run(message("Петров, Петров")) == accepted(Reason.BY_CAPTION, PETROV)

    def test_two_surnames(self):
        assert run(message("Мехоношин и Петров")) == review(Reason.MULTIPLE_EMPLOYEES)

    def test_two_surnames_even_with_binding(self):
        assert run(message("Мехоношин и Петров"), bound=PETROV) == review(
            Reason.MULTIPLE_EMPLOYEES
        )

    def test_partial_word_does_not_match(self):
        assert run(message("Мехоношина")) == review(Reason.EMPLOYEE_NOT_FOUND)


class TestNamesakes:
    def test_without_binding(self):
        assert run(message("Иванов")) == review(Reason.AMBIGUOUS_SURNAME)

    def test_binding_points_to_one_of_them(self):
        assert run(message("Иванов"), bound=IVANOV_PETR) == accepted(
            Reason.BY_CAPTION_AND_ACCOUNT, IVANOV_PETR
        )

    def test_binding_points_to_someone_else(self):
        assert run(message("Иванов"), bound=PETROV) == review(Reason.AMBIGUOUS_SURNAME)


class TestCaptionAndAccount:
    def test_caption_matches_binding(self):
        assert run(message("Мехоношин"), bound=MEKHONOSHIN) == accepted(
            Reason.BY_CAPTION_AND_ACCOUNT, MEKHONOSHIN
        )

    def test_caption_contradicts_binding(self):
        assert run(message("Мехоношин"), bound=PETROV) == review(Reason.CAPTION_ACCOUNT_MISMATCH)

    def test_unknown_surname_but_bound_account(self):
        assert run(message("заступил на пост"), bound=PETROV) == accepted(Reason.BY_ACCOUNT, PETROV)

    @pytest.mark.parametrize("caption", [None, "", "  "], ids=["none", "empty", "spaces"])
    def test_empty_caption_with_bound_account(self, caption):
        assert run(message(caption), bound=PETROV) == accepted(Reason.BY_ACCOUNT, PETROV)


class TestNotFound:
    def test_unknown_surname_without_binding(self):
        assert run(message("заступил на пост")) == review(Reason.EMPLOYEE_NOT_FOUND)

    @pytest.mark.parametrize("caption", [None, "", "  "], ids=["none", "empty", "spaces"])
    def test_no_caption_without_binding(self, caption):
        assert run(message(caption)) == review(Reason.NO_CAPTION)

    def test_caption_without_letters(self):
        assert run(message("👍")) == review(Reason.EMPLOYEE_NOT_FOUND)


class TestInactiveEmployee:
    def test_inactive_employee_not_matched_by_caption(self):
        assert run(message("Сидоров")) == review(Reason.EMPLOYEE_NOT_FOUND)

    def test_binding_to_inactive_employee_ignored(self):
        assert run(message(None), bound=SIDOROV_FIRED) == review(Reason.NO_CAPTION)

    def test_binding_to_inactive_does_not_conflict_with_caption(self):
        assert run(message("Петров"), bound=SIDOROV_FIRED) == accepted(Reason.BY_CAPTION, PETROV)


class TestAlbum:
    def test_album_part_without_caption_and_binding(self):
        assert run(message(None, media_group_id="album-1")) == Decision(
            MessageStatus.REJECTED, Reason.ALBUM_PART_WITHOUT_CAPTION, None, SHIFT_DAY
        )

    def test_album_part_without_caption_with_binding(self):
        assert run(message(None, media_group_id="album-1"), bound=PETROV) == accepted(
            Reason.BY_ACCOUNT, PETROV
        )

    def test_album_part_with_caption(self):
        assert run(message("Мехоношин", media_group_id="album-1")) == accepted(
            Reason.BY_CAPTION, MEKHONOSHIN
        )

    def test_album_part_with_unknown_caption_goes_to_review(self):
        assert run(message("на посту", media_group_id="album-1")) == review(
            Reason.EMPLOYEE_NOT_FOUND
        )


def test_index_skips_inactive_and_groups_namesakes():
    assert EMPLOYEES.by_surname["иванов"] == (IVANOV_IVAN, IVANOV_PETR)
    assert "сидоров" not in EMPLOYEES.by_surname
    assert SIDOROV_FIRED not in EMPLOYEES.active_ids
