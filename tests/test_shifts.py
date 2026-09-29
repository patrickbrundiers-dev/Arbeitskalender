"""Tests für Dienstdefinitionen und Terminzeiten (ohne Home Assistant)."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from _loader import load
import pytest

shifts = load("shifts")
BERLIN = ZoneInfo("Europe/Berlin")


def test_defaults_parse():
    parsed = shifts.parse_shifts(shifts.DEFAULT_SHIFTS_TEXT)
    assert list(parsed) == ["F", "F1", "F2", "F3", "F4", "S", "S1", "S2", "S3", "S4", "U", "K", "X"]
    assert parsed["F1"].kind == shifts.KIND_TIMED and parsed["F1"].hours == 6.5
    assert parsed["F"].kind == shifts.KIND_ALLDAY and parsed["F"].category == shifts.CAT_WORK
    assert parsed["U"].category == shifts.CAT_VACATION
    assert parsed["K"].category == shifts.CAT_ABSENCE
    assert parsed["X"].kind == shifts.KIND_OFF


def test_default_hours_match_times_where_no_break():
    parsed = shifts.parse_shifts(shifts.DEFAULT_SHIFTS_TEXT)
    for code in ("F1", "F2", "F3", "S1", "S2", "S3"):
        assert parsed[code].effective_hours == parsed[code].hours, code


def test_roundtrip():
    parsed = shifts.parse_shifts(shifts.DEFAULT_SHIFTS_TEXT)
    again = shifts.parse_shifts(shifts.shifts_to_text(parsed))
    assert again == parsed


def test_roundtrip_keeps_unknown_time_work_shift_as_work():
    parsed = shifts.parse_shifts("F;Früh\nK;Krank;;;abwesend")
    again = shifts.parse_shifts(shifts.shifts_to_text(parsed))
    assert again["F"].category == shifts.CAT_WORK
    assert again["K"].category == shifts.CAT_ABSENCE


def test_comments_and_blank_lines():
    parsed = shifts.parse_shifts("# Kommentar\n\nF;Früh;06:00;14:00\n")
    assert list(parsed) == ["F"]


def test_name_defaults_to_code():
    assert shifts.parse_shifts("F;;06:00;14:00")["F"].name == "F"


@pytest.mark.parametrize(
    "text",
    [
        "F;Früh;06:00",  # Ende fehlt
        "F;Früh;;14:00",  # Start fehlt
        "F;Früh;6-14;",  # kein HH:MM
        "F;Früh;25:00;14:00",  # ungültige Stunde
        ";Früh;06:00;14:00",  # Code fehlt
        "F;Früh;06:00;14:00\nf;Früh;06:00;14:00",  # doppelt (case-insensitiv)
        "F;Früh;06:00;14:00;komisch",  # unbekannter Typ
        "F;Früh;06:00;14:00;;rot",  # ungültige Farbe
        "F;Früh;06:00;14:00;;;abc",  # ungültige Stunden
        "F;Früh;06:00;14:00;;;25",  # zu viele Stunden
        "a;b;c;d;e;f;g;h",  # zu viele Felder
    ],
)
def test_invalid(text):
    with pytest.raises(shifts.ShiftParseError):
        shifts.parse_shifts(text)


def test_error_has_line_number():
    with pytest.raises(shifts.ShiftParseError) as err:
        shifts.parse_shifts("F;Früh;06:00;14:00\nS;Spät;13:00")
    assert err.value.line_no == 2


def test_hours_comma_and_dot():
    assert shifts.parse_shifts("F;Früh;;;;;6,5")["F"].hours == 6.5
    assert shifts.parse_shifts("F;Früh;;;;;6.25")["F"].hours == 6.25


def test_effective_hours():
    parsed = shifts.parse_shifts("F;Früh;06:00;14:00\nN;Nacht;21:00;06:00\nX;Früh ohne Zeit\nU;Urlaub;;;urlaub;;8")
    assert parsed["F"].effective_hours == 8
    assert parsed["N"].effective_hours == 9
    assert parsed["X"].effective_hours is None
    assert parsed["U"].effective_hours is None and parsed["U"].hours is None  # Abwesenheit hat keine Stunden


def test_find_shift_case_insensitive():
    parsed = shifts.parse_shifts("F1;Früh;06:00;14:00")
    assert shifts.find_shift(parsed, "f1") is parsed["F1"]
    assert shifts.find_shift(parsed, " F1 ") is parsed["F1"]
    assert shifts.find_shift(parsed, "Z9") is None
    assert shifts.find_shift(parsed, "") is None
    assert shifts.find_shift(parsed, None) is None


def test_timed_bounds():
    s = shifts.parse_shifts("F;Früh;06:00;14:00")["F"]
    start, end = shifts.event_bounds(s, date(2026, 9, 30), BERLIN)
    assert start == datetime(2026, 9, 30, 6, 0, tzinfo=BERLIN)
    assert end == datetime(2026, 9, 30, 14, 0, tzinfo=BERLIN)


def test_night_shift_ends_next_day():
    s = shifts.parse_shifts("N;Nacht;21:00;06:00")["N"]
    start, end = shifts.event_bounds(s, date(2026, 9, 30), BERLIN)
    assert start == datetime(2026, 9, 30, 21, 0, tzinfo=BERLIN)
    assert end == datetime(2026, 10, 1, 6, 0, tzinfo=BERLIN)
    assert end - start == timedelta(hours=9)


def test_night_shift_across_dst_change():
    # Sommerzeit endet am 25.10.2026: die Nacht ist real 10 Stunden lang
    s = shifts.parse_shifts("N;Nacht;21:00;06:00")["N"]
    start, end = shifts.event_bounds(s, date(2026, 10, 24), BERLIN)
    utc = ZoneInfo("UTC")
    assert (end.astimezone(utc) - start.astimezone(utc)).total_seconds() == 10 * 3600


def test_allday_and_off():
    parsed = shifts.parse_shifts("U;Urlaub;;;urlaub\nX;Frei;;;frei\nF;Früh")
    assert shifts.event_bounds(parsed["U"], date(2026, 9, 30), BERLIN) == (date(2026, 9, 30), date(2026, 10, 1))
    assert shifts.event_bounds(parsed["F"], date(2026, 9, 30), BERLIN) == (date(2026, 9, 30), date(2026, 10, 1))
    assert shifts.event_bounds(parsed["X"], date(2026, 9, 30), BERLIN) is None
    assert parsed["X"].creates_event is False
    assert parsed["U"].creates_event is True


def test_allday_ignores_times():
    s = shifts.parse_shifts("U;Urlaub;08:00;16:00;abwesend")["U"]
    assert s.start is None and s.end is None


def test_signature_changes_with_times_and_name():
    a = shifts.parse_shifts("F;Früh;06:00;14:00")["F"]
    assert a.signature() == shifts.parse_shifts("F;Früh;06:00;14:00")["F"].signature()
    assert a.signature() != shifts.parse_shifts("F;Früh;06:30;14:00")["F"].signature()
    assert a.signature() != shifts.parse_shifts("F;Frühdienst;06:00;14:00")["F"].signature()
    # Farbe und Stunden ändern den Termin nicht
    assert a.signature() == shifts.parse_shifts("F;Früh;06:00;14:00;;#ff0000;7")["F"].signature()


def test_as_dict():
    s = shifts.parse_shifts("F;Früh;06:00;14:00;;#FFAA00;7,5")["F"]
    assert s.as_dict() == {
        "code": "F",
        "name": "Früh",
        "start": "06:00",
        "end": "14:00",
        "kind": "timed",
        "category": "work",
        "color": "#ffaa00",
        "hours": 7.5,
    }
