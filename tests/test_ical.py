"""Tests für den iCal-Feed (ohne Home Assistant)."""

from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from _loader import load

ical = load("ical")
BERLIN = ZoneInfo("Europe/Berlin")
NOW = datetime(2026, 9, 29, 6, 0, tzinfo=timezone.utc)


def _lines(text: str) -> list[str]:
    assert text.endswith("\r\n") and "\n" not in text.replace("\r\n", "")
    return text.split("\r\n")[:-1]


def test_timed_event_is_utc():
    ev = ical.IcsEvent("e1-2026-09-29", "Frühdienst 1", datetime(2026, 9, 29, 6, 30, tzinfo=BERLIN), datetime(2026, 9, 29, 13, 0, tzinfo=BERLIN), "Kürzel: F1")
    lines = _lines(ical.build_ics("Jenny", [ev], NOW))
    assert lines[0] == "BEGIN:VCALENDAR" and lines[-1] == "END:VCALENDAR"
    assert "DTSTART:20260929T043000Z" in lines  # 06:30 MESZ = 04:30 UTC
    assert "DTEND:20260929T110000Z" in lines
    assert "SUMMARY:Frühdienst 1" in lines
    assert "UID:e1-2026-09-29" in lines
    assert "DTSTAMP:20260929T060000Z" in lines
    assert "X-WR-CALNAME:Jenny" in lines


def test_allday_event_uses_date_values():
    ev = ical.IcsEvent("u", "Urlaub", date(2026, 10, 1), date(2026, 10, 2))
    lines = _lines(ical.build_ics("x", [ev], NOW))
    assert "DTSTART;VALUE=DATE:20261001" in lines and "DTEND;VALUE=DATE:20261002" in lines
    assert "TRANSP:TRANSPARENT" in lines
    assert not any(line.startswith("DESCRIPTION") for line in lines)


def test_text_is_escaped():
    ev = ical.IcsEvent("u", "A, B; C\\D", date(2026, 10, 1), date(2026, 10, 2), "Zeile1\nZeile2")
    lines = _lines(ical.build_ics("x", [ev], NOW))
    assert "SUMMARY:A\\, B\\; C\\\\D" in lines
    assert "DESCRIPTION:Zeile1\\nZeile2" in lines


def test_long_lines_are_folded_at_75_octets():
    ev = ical.IcsEvent("u", "Ä" * 80, date(2026, 10, 1), date(2026, 10, 2))
    text = ical.build_ics("x", [ev], NOW)
    lines = _lines(text)
    assert all(len(line.encode("utf-8")) <= 75 for line in lines)
    # Entfalten ergibt wieder den Originaltext
    unfolded = text.replace("\r\n ", "")
    assert "SUMMARY:" + "Ä" * 80 in unfolded


def test_empty_calendar_is_valid():
    lines = _lines(ical.build_ics("x", [], NOW))
    assert lines[0] == "BEGIN:VCALENDAR" and lines[-1] == "END:VCALENDAR" and "BEGIN:VEVENT" not in lines
