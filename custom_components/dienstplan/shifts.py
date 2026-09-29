"""Reine Logik für den Dienstplan (ohne Home-Assistant-Abhängigkeiten).

Eine Dienstdefinition ist eine Zeile im Format::

    Code;Name;Start;Ende;Typ;Farbe

* ``Code``   – Kürzel wie im Dienstplan (z. B. ``F1``, ``S2``, ``N1``, ``U``)
* ``Name``   – Bezeichnung des Kalendertermins (z. B. ``Frühdienst 1``)
* ``Start``/``Ende`` – ``HH:MM``; beide leer = Ganztagstermin.
  Liegt ``Ende`` vor oder gleich ``Start``, endet der Dienst am Folgetag
  (Nachtdienst).
* ``Typ``    – optional: ``frei`` = kein Kalendereintrag (z. B. ``X``),
  ``abwesend`` = Ganztagstermin (z. B. Urlaub/Krank). Ohne Angabe: Dienst.
* ``Farbe``  – optional: ``#RRGGBB`` für die Karte.

Leere Zeilen und Zeilen, die mit ``#`` beginnen, werden ignoriert.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, tzinfo
import re

KIND_TIMED = "timed"
KIND_ALLDAY = "allday"
KIND_OFF = "off"

_TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})$")
_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")

TYPE_OFF = {"frei", "off"}
TYPE_ALLDAY = {"abwesend", "ganztag", "allday"}
TYPE_SHIFT = {"", "dienst", "shift"}


class ShiftParseError(ValueError):
    """Eine Zeile der Dienstdefinition ist ungültig."""

    def __init__(self, line_no: int, message: str) -> None:
        super().__init__(f"Zeile {line_no}: {message}")
        self.line_no = line_no
        self.message = message


@dataclass(frozen=True)
class Shift:
    """Ein Dienst wie im Dienstplan definiert."""

    code: str
    name: str
    start: time | None
    end: time | None
    kind: str
    color: str | None = None

    @property
    def creates_event(self) -> bool:
        """Ob für diesen Dienst ein Kalendertermin entsteht."""
        return self.kind != KIND_OFF

    def as_dict(self) -> dict:
        """Für die Karte (Websocket)."""
        return {
            "code": self.code,
            "name": self.name,
            "start": self.start.strftime("%H:%M") if self.start else None,
            "end": self.end.strftime("%H:%M") if self.end else None,
            "kind": self.kind,
            "color": self.color,
        }


def _parse_time(value: str, line_no: int) -> time:
    match = _TIME_RE.match(value)
    if not match:
        raise ShiftParseError(line_no, f"Uhrzeit „{value}“ ungültig (erwartet HH:MM)")
    hour, minute = int(match.group(1)), int(match.group(2))
    if hour > 23 or minute > 59:
        raise ShiftParseError(line_no, f"Uhrzeit „{value}“ ungültig")
    return time(hour, minute)


def parse_shifts(text: str) -> dict[str, Shift]:
    """Dienstdefinitionen aus Text lesen (Reihenfolge bleibt erhalten)."""
    shifts: dict[str, Shift] = {}
    for line_no, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split(";")]
        if len(parts) > 6:
            raise ShiftParseError(line_no, "zu viele Felder (max. 6)")
        parts += [""] * (6 - len(parts))
        code, name, start_s, end_s, type_s, color_s = parts

        if not code:
            raise ShiftParseError(line_no, "Code fehlt")
        key = code.casefold()
        if any(existing.casefold() == key for existing in shifts):
            raise ShiftParseError(line_no, f"Code „{code}“ ist doppelt")

        if bool(start_s) != bool(end_s):
            raise ShiftParseError(line_no, "Start und Ende müssen beide angegeben sein oder beide fehlen")
        start = _parse_time(start_s, line_no) if start_s else None
        end = _parse_time(end_s, line_no) if end_s else None

        type_key = type_s.casefold()
        if type_key in TYPE_OFF:
            kind = KIND_OFF
        elif type_key in TYPE_ALLDAY:
            kind = KIND_ALLDAY
        elif type_key in TYPE_SHIFT:
            kind = KIND_TIMED if start else KIND_ALLDAY
        else:
            raise ShiftParseError(line_no, f"Typ „{type_s}“ unbekannt (frei, abwesend oder leer)")

        if kind == KIND_ALLDAY:
            start = end = None

        color: str | None = None
        if color_s:
            if not _COLOR_RE.match(color_s):
                raise ShiftParseError(line_no, f"Farbe „{color_s}“ ungültig (erwartet #RRGGBB)")
            color = color_s.lower()

        shifts[code] = Shift(code, name or code, start, end, kind, color)
    return shifts


def find_shift(shifts: dict[str, Shift], code: str | None) -> Shift | None:
    """Dienst zu einem Code finden (Groß-/Kleinschreibung egal)."""
    if not code:
        return None
    if code in shifts:
        return shifts[code]
    folded = code.strip().casefold()
    for key, shift in shifts.items():
        if key.casefold() == folded:
            return shift
    return None


def event_bounds(shift: Shift, day: date, tz: tzinfo) -> tuple[date, date] | tuple[datetime, datetime] | None:
    """Beginn/Ende des Termins für einen Tag.

    * Ganztag: ``(day, day + 1)`` (Ende exklusiv wie im HA-Kalender)
    * Zeitlich: zeitzonenbehaftete ``datetime``; Nachtdienste enden am Folgetag
    * ``None``: kein Termin (Typ ``frei``)
    """
    if shift.kind == KIND_OFF:
        return None
    if shift.kind == KIND_ALLDAY or shift.start is None or shift.end is None:
        return day, day + timedelta(days=1)
    start = datetime.combine(day, shift.start, tzinfo=tz)
    end_day = day if shift.end > shift.start else day + timedelta(days=1)
    end = datetime.combine(end_day, shift.end, tzinfo=tz)
    return start, end


def shifts_to_text(shifts: dict[str, Shift]) -> str:
    """Dienste wieder in das Textformat bringen."""
    lines = []
    for shift in shifts.values():
        start = shift.start.strftime("%H:%M") if shift.start else ""
        end = shift.end.strftime("%H:%M") if shift.end else ""
        kind = {KIND_OFF: "frei", KIND_ALLDAY: "abwesend" if not shift.start else ""}.get(shift.kind, "")
        parts = [shift.code, shift.name, start, end, kind, shift.color or ""]
        while parts and parts[-1] == "":
            parts.pop()
        lines.append(";".join(parts))
    return "\n".join(lines)


# Platzhalter-Zeiten: bitte mit dem Aushang abgleichen!
DEFAULT_SHIFTS_TEXT = "\n".join(
    [f"F{i};Frühdienst {i};06:00;14:00" for i in range(1, 6)]
    + [f"Z{i};Zwischendienst {i};10:00;18:00" for i in range(1, 6)]
    + [f"S{i};Spätdienst {i};13:00;21:00" for i in range(1, 6)]
    + [f"N{i};Nachtdienst {i};21:00;06:00" for i in range(1, 6)]
    + ["U;Urlaub;;;abwesend", "K;Krank;;;abwesend", "X;Frei;;;frei"]
)
