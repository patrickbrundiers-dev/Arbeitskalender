"""Tests für die reine Dienstplan-Logik (ohne Home Assistant)."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
import importlib.util
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "shifts",
    Path(__file__).parent.parent / "custom_components" / "dienstplan" / "shifts.py",
)
shifts = importlib.util.module_from_spec(_SPEC)
import sys

sys.modules["shifts"] = shifts
_SPEC.loader.exec_module(shifts)

BERLIN = ZoneInfo("Europe/Berlin")


def test_defaults_parse():
    parsed = shifts.parse_shifts(shifts.DEFAULT_SHIFTS_TEXT)
    assert len(parsed) == 23
    assert parsed["F1"].kind == shifts.KIND_TIMED
    assert parsed["U"].kind == shifts.KIND_ALLDAY
    assert parsed["X"].kind == shifts.KIND_OFF
    assert list(parsed)[0] == "F1"  # Reihenfolge bleibt erhalten


def test_roundtrip():
    parsed = shifts.parse_shifts(shifts.DEFAULT_SHIFTS_TEXT)
    again = shifts.parse_shifts(shifts.shifts_to_text(parsed))
    assert again == parsed


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
        "a;b;c;d;e;f;g",  # zu viele Felder
    ],
)
def test_invalid(text):
    with pytest.raises(shifts.ShiftParseError):
        shifts.parse_shifts(text)


def test_error_has_line_number():
    with pytest.raises(shifts.ShiftParseError) as err:
        shifts.parse_shifts("F;Früh;06:00;14:00\nS;Spät;13:00")
    assert err.value.line_no == 2


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
    assert (end - start).total_seconds() == 10 * 3600 or (end.astimezone(ZoneInfo("UTC")) - start.astimezone(ZoneInfo("UTC"))).total_seconds() == 10 * 3600


def test_allday_and_off():
    parsed = shifts.parse_shifts("U;Urlaub;;;abwesend\nX;Frei;;;frei")
    assert shifts.event_bounds(parsed["U"], date(2026, 9, 30), BERLIN) == (date(2026, 9, 30), date(2026, 10, 1))
    assert shifts.event_bounds(parsed["X"], date(2026, 9, 30), BERLIN) is None
    assert parsed["X"].creates_event is False
    assert parsed["U"].creates_event is True


def test_allday_ignores_times():
    s = shifts.parse_shifts("U;Urlaub;08:00;16:00;abwesend")["U"]
    assert s.start is None and s.end is None


def test_as_dict():
    s = shifts.parse_shifts("F;Früh;06:00;14:00;;#FFAA00")["F"]
    assert s.as_dict() == {
        "code": "F",
        "name": "Früh",
        "start": "06:00",
        "end": "14:00",
        "kind": "timed",
        "color": "#ffaa00",
    }
