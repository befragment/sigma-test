from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

import pytest

from app.domain.errors import ValidationError
from app.domain.models import Group
from app.domain.rules import caption_words, message_link, shift_date, surname_norm

MSK = ZoneInfo("Europe/Moscow")

DAY = Group(chat_id=-1001, title="day", window_start=time(7, 0), window_end=time(10, 0))
NIGHT = Group(chat_id=-1002, title="night", window_start=time(20, 0), window_end=time(8, 0))


def msk(*args: int) -> datetime:
    return datetime(*args, tzinfo=MSK)


class TestNormalization:
    def test_caption_words_lowercase_yo_and_punctuation(self):
        assert caption_words("ЁЛКИН, на смене!!! 👍 #пост 12") == ["елкин", "на", "смене", "пост"]

    def test_double_surname_kept_whole(self):
        assert caption_words("Петров-Водкин заступил") == ["петров-водкин", "заступил"]

    def test_empty_caption(self):
        assert caption_words(None) == []
        assert caption_words("   ") == []

    def test_surname_is_first_word_of_full_name(self):
        assert surname_norm("Мехоношин Алексей Петрович") == "мехоношин"

    def test_explicit_surname_wins(self):
        assert surname_norm("Алексей Мехоношин", surname="Мехоношин") == "мехоношин"

    def test_surname_with_yo(self):
        assert surname_norm("Сёмин Олег") == "семин"

    def test_no_letters_rejected(self):
        with pytest.raises(ValidationError):
            surname_norm("123 !!!")


class TestShiftDateDayWindow:
    @pytest.mark.parametrize(
        "moment",
        [msk(2025, 9, 19, 7, 0), msk(2025, 9, 19, 8, 50, 6), msk(2025, 9, 19, 10, 0, 59)],
        ids=["start-inclusive", "inside", "end-inclusive-minute"],
    )
    def test_inside_window_gives_local_date(self, moment):
        assert shift_date(moment, DAY) == date(2025, 9, 19)

    @pytest.mark.parametrize(
        "moment",
        [msk(2025, 9, 19, 6, 59, 59), msk(2025, 9, 19, 10, 1), msk(2025, 9, 19, 23, 0)],
        ids=["before-start", "after-end", "evening"],
    )
    def test_outside_window(self, moment):
        assert shift_date(moment, DAY) is None

    def test_utc_converted_to_group_tz(self):
        # 05:30 UTC = 08:30 MSK
        assert shift_date(datetime(2025, 9, 19, 5, 30, tzinfo=UTC), DAY) == date(2025, 9, 19)

    def test_naive_datetime_treated_as_utc(self):
        assert shift_date(datetime(2025, 9, 19, 5, 30), DAY) == date(2025, 9, 19)

    def test_other_timezone(self):
        group = Group(-1003, "nsk", time(7, 0), time(10, 0), tz="Asia/Novosibirsk")
        # 08:00 по Новосибирску = 04:00 по Москве: окно считается по местному времени группы
        assert shift_date(datetime(2025, 9, 19, 1, 0, tzinfo=UTC), group) == date(2025, 9, 19)
        assert shift_date(msk(2025, 9, 19, 8, 0), group) is None


class TestShiftDateOvernightWindow:
    @pytest.mark.parametrize(
        ("moment", "expected"),
        [
            (msk(2025, 9, 18, 20, 0), date(2025, 9, 18)),
            (msk(2025, 9, 18, 23, 59, 59), date(2025, 9, 18)),
            (msk(2025, 9, 19, 0, 0), date(2025, 9, 18)),
            (msk(2025, 9, 19, 7, 59), date(2025, 9, 18)),
            (msk(2025, 9, 19, 8, 0), date(2025, 9, 18)),
        ],
        ids=["start", "before-midnight", "midnight", "morning", "end-inclusive"],
    )
    def test_both_sides_of_midnight_belong_to_evening_date(self, moment, expected):
        assert shift_date(moment, NIGHT) == expected

    @pytest.mark.parametrize(
        "moment",
        [msk(2025, 9, 19, 8, 1), msk(2025, 9, 19, 12, 0), msk(2025, 9, 19, 19, 59)],
        ids=["just-after-end", "noon", "just-before-start"],
    )
    def test_outside_window(self, moment):
        assert shift_date(moment, NIGHT) is None

    def test_utc_date_differs_from_local(self):
        # 21:30 UTC 18.09 = 00:30 MSK 19.09 → смена вечера 18.09
        assert shift_date(datetime(2025, 9, 18, 21, 30, tzinfo=UTC), NIGHT) == date(2025, 9, 18)

    def test_first_day_of_month_morning_goes_to_previous_month(self):
        assert shift_date(msk(2025, 10, 1, 6, 0), NIGHT) == date(2025, 9, 30)


class TestGroupValidation:
    def test_equal_bounds_forbidden(self):
        with pytest.raises(ValidationError):
            Group(-1, "g", time(8, 0), time(8, 0))

    def test_unknown_timezone(self):
        with pytest.raises(ValidationError):
            Group(-1, "g", time(8, 0), time(9, 0), tz="Mars/Olympus")

    def test_default_timezone_is_moscow(self):
        assert Group(-1, "g", time(8, 0), time(9, 0)).tz == "Europe/Moscow"


class TestMessageLink:
    def test_supergroup(self):
        assert message_link(-1001234567890, 42) == "https://t.me/c/1234567890/42"

    def test_basic_group_has_no_link(self):
        assert message_link(-123456, 42) is None
