"""Reine Logik für den Dienstplan (ohne Home-Assistant-Abhängigkeiten).

Eine Dienstdefinition ist eine Zeile im Format::

    Code;Name;Start;Ende;Typ;Farbe;Std

* ``Code``   – Kürzel wie im Dienstplan (z. B. ``F1``, ``S2``, ``N1``, ``U``)
* ``Name``   – Bezeichnung des Kalendertermins (z. B. ``Frühdienst 1``)
* ``Start``/``Ende`` – ``HH:MM``; beide leer = Ganztagstermin.
  Liegt ``Ende`` vor oder gleich ``Start``, endet der Dienst am Folgetag
  (Nachtdienst).
* ``Typ``    – optional: ``frei`` = kein Kalendereintrag (z. B. ``X``),
  ``urlaub`` = Ganztagstermin, zählt als Urlaubstag,
  ``abwesend`` = Ganztagstermin (z. B. Krank). Ohne Angabe: Dienst.
* ``Farbe``  – optional: ``#RRGGBB`` für die Karte.
* ``Std``    – optional: bezahlte Stunden des Dienstes (z. B. ``6,5``).
  Ohne Angabe wird die Dauer zwischen Start und Ende verwendet.

Leere Zeilen und Zeilen, die mit ``#`` beginnen, werden ignoriert.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, tzinfo
import re

KIND_TIMED = "timed"
KIND_ALLDAY = "allday"
KIND_OFF = "off"

CAT_WORK = "work"
CAT_ABSENCE = "absence"
CAT_VACATION = "vacation"
CAT_OFF = "off"

_TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})$")
_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
_HOURS_RE = re.compile(r"^\d{1,2}([.,]\d{1,2})?$")

TYPE_OFF = {"frei", "off"}
TYPE_VACATION = {"urlaub", "vacation"}
TYPE_ABSENCE = {"abwesend", "ganztag", "allday"}
TYPE_SHIFT = {"", "dienst", "shift"}

MAX_FIELDS = 7


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
    hours: float | None = None  # explizit angegebene Stunden
    category: str = CAT_WORK

    @property
    def creates_event(self) -> bool:
        """Ob für diesen Dienst ein Kalendertermin entsteht."""
        return self.kind != KIND_OFF

    @property
    def effective_hours(self) -> float | None:
        """Stunden des Dienstes (explizit oder aus Start/Ende)."""
        if self.category != CAT_WORK:
            return None
        if self.hours is not None:
            return self.hours
        if self.start is None or self.end is None:
            return None
        minutes = (self.end.hour * 60 + self.end.minute) - (self.start.hour * 60 + self.start.minute)
        if minutes <= 0:
            minutes += 24 * 60
        return round(minutes / 60, 2)

    def signature(self) -> str:
        """Kennung des Termininhalts, um geänderte Definitionen zu erkennen."""
        start = self.start.strftime("%H:%M") if self.start else ""
        end = self.end.strftime("%H:%M") if self.end else ""
        return f"{self.code}|{self.name}|{start}|{end}|{self.kind}"

    def as_dict(self) -> dict:
        """Für die Karte (Websocket)."""
        return {
            "code": self.code,
            "name": self.name,
            "start": self.start.strftime("%H:%M") if self.start else None,
            "end": self.end.strftime("%H:%M") if self.end else None,
            "kind": self.kind,
            "category": self.category,
            "color": self.color,
            "hours": self.effective_hours,
        }


def _parse_time(value: str, line_no: int) -> time:
    match = _TIME_RE.match(value)
    if not match:
        raise ShiftParseError(line_no, f"Uhrzeit „{value}“ ungültig (erwartet HH:MM)")
    hour, minute = int(match.group(1)), int(match.group(2))
    if hour > 23 or minute > 59:
        raise ShiftParseError(line_no, f"Uhrzeit „{value}“ ungültig")
    return time(hour, minute)


def _parse_hours(value: str, line_no: int) -> float:
    if not _HOURS_RE.match(value):
        raise ShiftParseError(line_no, f"Stunden „{value}“ ungültig (erwartet z. B. 6,5)")
    hours = float(value.replace(",", "."))
    if hours > 24:
        raise ShiftParseError(line_no, f"Stunden „{value}“ ungültig (max. 24)")
    return hours


def parse_shifts(text: str) -> dict[str, Shift]:
    """Dienstdefinitionen aus Text lesen (Reihenfolge bleibt erhalten)."""
    shifts: dict[str, Shift] = {}
    for line_no, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split(";")]
        if len(parts) > MAX_FIELDS:
            raise ShiftParseError(line_no, f"zu viele Felder (max. {MAX_FIELDS})")
        parts += [""] * (MAX_FIELDS - len(parts))
        code, name, start_s, end_s, type_s, color_s, hours_s = parts

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
            category, kind = CAT_OFF, KIND_OFF
        elif type_key in TYPE_VACATION:
            category, kind = CAT_VACATION, KIND_ALLDAY
        elif type_key in TYPE_ABSENCE:
            category, kind = CAT_ABSENCE, KIND_ALLDAY
        elif type_key in TYPE_SHIFT:
            category, kind = CAT_WORK, (KIND_TIMED if start else KIND_ALLDAY)
        else:
            raise ShiftParseError(line_no, f"Typ „{type_s}“ unbekannt (frei, urlaub, abwesend oder leer)")

        if kind != KIND_TIMED:
            start = end = None

        color: str | None = None
        if color_s:
            if not _COLOR_RE.match(color_s):
                raise ShiftParseError(line_no, f"Farbe „{color_s}“ ungültig (erwartet #RRGGBB)")
            color = color_s.lower()

        hours = _parse_hours(hours_s, line_no) if hours_s else None
        if category != CAT_WORK:
            hours = None

        shifts[code] = Shift(code, name or code, start, end, kind, color, hours, category)
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


_CATEGORY_TYPE = {CAT_OFF: "frei", CAT_VACATION: "urlaub", CAT_ABSENCE: "abwesend", CAT_WORK: ""}


def shifts_to_text(shifts: dict[str, Shift]) -> str:
    """Dienste wieder in das Textformat bringen."""
    lines = []
    for shift in shifts.values():
        parts = [
            shift.code,
            shift.name,
            shift.start.strftime("%H:%M") if shift.start else "",
            shift.end.strftime("%H:%M") if shift.end else "",
            _CATEGORY_TYPE[shift.category],
            shift.color or "",
            f"{shift.hours:g}".replace(".", ",") if shift.hours is not None else "",
        ]
        while parts and parts[-1] == "":
            parts.pop()
        lines.append(";".join(parts))
    return "\n".join(lines)


# Aus dem Foto der Legende gelesen. Sicher lesbar waren nur die Stunden
# (F1 6,5 / F2 6 / F3 4 und S1 6,5 / S2 6 / S3 4); die Uhrzeiten sind daraus
# abgeleitet und müssen mit dem Aushang abgeglichen werden. Dienste ohne Zeiten
# (F, S, F4, S4) erzeugen zunächst Ganztagstermine.
DEFAULT_SHIFTS_TEXT = "\n".join(
    [
        "F;Frühdienst",
        "F1;Frühdienst 1;06:30;13:00;;;6,5",
        "F2;Frühdienst 2;07:00;13:00;;;6",
        "F3;Frühdienst 3;07:00;11:00;;;4",
        "F4;Frühdienst 4",
        "S;Spätdienst",
        "S1;Spätdienst 1;13:30;20:00;;;6,5",
        "S2;Spätdienst 2;14:00;20:00;;;6",
        "S3;Spätdienst 3;17:00;21:00;;;4",
        "S4;Spätdienst 4",
        "U;Urlaub;;;urlaub",
        "K;Krank;;;abwesend",
        "X;Frei;;;frei",
    ]
)
