"""iCalendar-Feed (RFC 5545) für den Dienstplan (ohne Home-Assistant-Abhängigkeiten)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone


@dataclass(frozen=True)
class IcsEvent:
    """Ein Termin des Feeds. ``start``/``end``: ``date`` (ganztägig, Ende exklusiv) oder aware ``datetime``."""

    uid: str
    summary: str
    start: date | datetime
    end: date | datetime
    description: str = ""


def _escape(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
    )


def _fold(line: str) -> list[str]:
    """Zeilen auf höchstens 75 Oktette umbrechen (Fortsetzung mit führendem Leerzeichen)."""
    encoded = line.encode("utf-8")
    if len(encoded) <= 75:
        return [line]
    out: list[str] = []
    current = ""
    limit = 75
    for char in line:
        if len((current + char).encode("utf-8")) > limit:
            out.append(current)
            current = char
            limit = 74  # führendes Leerzeichen zählt mit
        else:
            current += char
    if current:
        out.append(current)
    return [out[0]] + [" " + part for part in out[1:]]


def _utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def build_ics(name: str, events: list[IcsEvent], now: datetime) -> str:
    """Kalender als Text (CRLF-Zeilenenden)."""
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Dienstplan//Home Assistant//DE",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_escape(name)}",
        "X-PUBLISHED-TTL:PT1H",
        "REFRESH-INTERVAL;VALUE=DURATION:PT1H",
    ]
    stamp = _utc(now)
    for event in events:
        lines.append("BEGIN:VEVENT")
        lines.append(f"UID:{event.uid}")
        lines.append(f"DTSTAMP:{stamp}")
        if isinstance(event.start, datetime):
            lines.append(f"DTSTART:{_utc(event.start)}")
            lines.append(f"DTEND:{_utc(event.end)}")  # type: ignore[arg-type]
        else:
            lines.append(f"DTSTART;VALUE=DATE:{event.start:%Y%m%d}")
            lines.append(f"DTEND;VALUE=DATE:{event.end:%Y%m%d}")
            lines.append("TRANSP:TRANSPARENT")
        lines.append(f"SUMMARY:{_escape(event.summary)}")
        if event.description:
            lines.append(f"DESCRIPTION:{_escape(event.description)}")
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")

    folded: list[str] = []
    for line in lines:
        folded.extend(_fold(line))
    return "\r\n".join(folded) + "\r\n"
