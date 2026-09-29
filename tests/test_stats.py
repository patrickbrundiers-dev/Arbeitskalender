"""Tests für Wochenstunden, Bilanz und Urlaubstage (ohne Home Assistant)."""

from __future__ import annotations

from datetime import date

from _loader import load

shifts = load("shifts")
stats = load("stats")

SHIFTS = shifts.parse_shifts(
    "F;Früh;;;;;6,5\nF1;Früh 1;06:30;13:00;;;6,5\nS;Spät;14:00;20:00\nN;Nacht;21:00;06:00\n"
    "G;Ohne Zeit\nU;Urlaub;;;urlaub\nK;Krank;;;abwesend\nX;Frei;;;frei"
)


def test_week_start():
    assert stats.week_start(date(2026, 9, 29)) == date(2026, 9, 28)  # Dienstag -> Montag
    assert stats.week_start(date(2026, 9, 28)) == date(2026, 9, 28)
    assert stats.week_start(date(2026, 10, 4)) == date(2026, 9, 28)  # Sonntag


def test_simple_week():
    days = {"2026-09-28": "F1", "2026-09-29": "F1", "2026-09-30": "S", "2026-10-01": "X"}
    result = stats.week_stats(days, SHIFTS, date(2026, 9, 28))
    assert result == {"hours": 19.0, "target": None, "balance": None, "missing": 0}


def test_balance_with_target_and_absence_credit():
    days = {
        "2026-09-28": "F1",  # 6,5
        "2026-09-29": "U",  # Gutschrift 38,5 / 5 = 7,7
        "2026-09-30": "K",  # 7,7
        "2026-10-03": "U",  # Samstag: keine Gutschrift
    }
    result = stats.week_stats(days, SHIFTS, date(2026, 9, 28), weekly_target=38.5)
    assert result["hours"] == 21.9
    assert result["balance"] == -16.6
    assert result["target"] == 38.5


def test_absence_without_target_gives_no_credit():
    result = stats.week_stats({"2026-09-29": "U"}, SHIFTS, date(2026, 9, 28))
    assert result["hours"] == 0 and result["balance"] is None


def test_missing_hours_are_counted_not_guessed():
    result = stats.week_stats({"2026-09-28": "G", "2026-09-29": "F1"}, SHIFTS, date(2026, 9, 28))
    assert result["hours"] == 6.5 and result["missing"] == 1


def test_night_shift_counts_on_start_day():
    days = {"2026-10-04": "N"}  # Sonntag -> gehört zur Woche ab 28.09.
    assert stats.week_stats(days, SHIFTS, date(2026, 9, 28))["hours"] == 9
    assert stats.week_stats(days, SHIFTS, date(2026, 10, 5))["hours"] == 0


def test_unknown_code_is_ignored():
    assert stats.week_stats({"2026-09-28": "??"}, SHIFTS, date(2026, 9, 28))["hours"] == 0


def test_range_covers_all_weeks():
    result = stats.stats_for_range({"2026-10-06": "F1"}, SHIFTS, date(2026, 8, 31), date(2026, 10, 11))
    assert list(result) == [
        "2026-08-31", "2026-09-07", "2026-09-14", "2026-09-21", "2026-09-28", "2026-10-05",
    ]
    assert result["2026-10-05"]["hours"] == 6.5 and result["2026-09-28"]["hours"] == 0


def test_vacation_days_only_workdays_of_the_year():
    days = {
        "2026-09-28": "U", "2026-09-29": "U",
        "2026-10-03": "U",  # Samstag: zählt nicht
        "2026-09-30": "K",  # krank: kein Urlaub
        "2025-12-31": "U",  # anderes Jahr
        "2026-10-01": "F1",
    }
    assert stats.vacation_days_taken(days, SHIFTS, 2026) == 2
    assert stats.vacation_days_taken(days, SHIFTS, 2025) == 1
    assert stats.vacation_days_taken(days, SHIFTS, 2024) == 0
