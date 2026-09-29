"""Sprachantworten: „Wie arbeitet Jenny morgen?“ als fertiger deutscher Satz.

Reine Logik ohne Home-Assistant-Importe (dadurch gut testbar). Der Service
``dienstplan.ask`` reicht die Sätze an Alexa, Assist oder eigene Skripte weiter.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
import re

from .shifts import CAT_ABSENCE, CAT_OFF, CAT_VACATION, CAT_WORK, Shift

LOOKAHEAD_DAYS = 90

MONTHS = [
    "Januar", "Februar", "März", "April", "Mai", "Juni",
    "Juli", "August", "September", "Oktober", "November", "Dezember",
]
WEEKDAYS = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]

_RELATIVE = {
    "heute": 0, "today": 0,
    "morgen": 1, "tomorrow": 1,
    "übermorgen": 2, "uebermorgen": 2,
    "gestern": -1, "yesterday": -1,
    "vorgestern": -2,
}
_WEEKDAY_INDEX = {
    "montag": 0, "monday": 0, "dienstag": 1, "tuesday": 1, "mittwoch": 2, "wednesday": 2,
    "donnerstag": 3, "thursday": 3, "freitag": 4, "friday": 4, "samstag": 5, "sonnabend": 5,
    "saturday": 5, "sonntag": 6, "sunday": 6,
}
_NEXT_WORDS = {"nächster", "nächste", "nächstes", "naechster", "naechste", "next", "wieder", "demnächst"}
_EVERYONE = {"wer", "alle", "jeder", "jede", "alle beide"}
_SICK = {"krank", "krankheit", "krankmeldung"}
_FILLER = (
    set(_RELATIVE) | set(_WEEKDAY_INDEX) | _NEXT_WORDS
    | {"am", "an", "den", "dem", "für", "fuer", "um", "im", "abend", "abends", "früh", "morgens", "vormittag",
       "nachmittag", "mittag", "nacht", "dienst", "arbeiten", "arbeit", "arbeitet", "eigentlich", "denn", "mal",
       "noch", "schon", "jetzt", "bitte", "wie", "wann", "wo", "was", "hat", "muss", "hatte", "als"}
)
_DATE_TOKEN = re.compile(r"[\d.:\-t]+")


def _tokens(text: str | None) -> list[str]:
    return re.findall(r"[\wäöüßÄÖÜ.\-:]+", text or "")


@dataclass(frozen=True)
class Person:
    """Eine Person mit Dienstplan (ein Home-Assistant-Eintrag)."""

    name: str
    entity_id: str | None
    shift_on: Callable[[date], Shift | None]


def display_name(title: str) -> str:
    """Name zum Vorlesen: „Dienstplan Jenny“ -> „Jenny“."""
    words = [w for w in title.split() if w.strip(":-–").casefold() != "dienstplan"]
    return " ".join(words) or title.strip() or "Dienstplan"


# ---------------------------------------------------------------------- Tag verstehen


def wants_next(text: str | None) -> bool:
    """„nächster“, „wieder“ … irgendwo im Text (auch in einem ganzen Satz)."""
    return any(t.casefold() in _NEXT_WORDS for t in _tokens(text))


def _parse_token(value: str, today: date) -> date | None:
    if value in _RELATIVE:
        return today + timedelta(days=_RELATIVE[value])
    if value in _WEEKDAY_INDEX:
        return today + timedelta(days=(_WEEKDAY_INDEX[value] - today.weekday()) % 7)
    match = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})(?:t.*)?", value)
    if match:
        try:
            return date(int(match[1]), int(match[2]), int(match[3]))
        except ValueError:
            return None
    match = re.fullmatch(r"(\d{1,2})\.(\d{1,2})\.?(\d{4})?", value)
    if match:
        try:
            return date(int(match[3] or today.year), int(match[2]), int(match[1]))
        except ValueError:
            return None
    return None


def parse_day(text: str | None, today: date) -> date | None:
    """Tag aus Text oder ganzem Satz: heute/morgen/…, Wochentag (nächster), 2026-10-05 oder 5.10.[2026].

    Ohne Tagesangabe gilt heute. Ist eine Zahlen-/Datumsangabe erkennbar, aber nicht zu
    verstehen (z. B. Alexa-Woche „2026-W41“ oder 30.2.), ist das Ergebnis ``None``.
    """
    tokens = [t.casefold() if t[:1].isdigit() else t.casefold().strip(".,:;!?") for t in _tokens(text)]
    tokens = [t for t in tokens if t]
    for token in tokens:
        found = _parse_token(token, today)
        if found is not None:
            return found
    if any(re.fullmatch(r"\d{4}-w\d+.*", t) or (_DATE_TOKEN.fullmatch(t) and any(c.isdigit() for c in t)) for t in tokens):
        return None
    return today


def day_phrase(day: date, today: date) -> str:
    offset = (day - today).days
    fixed = {0: "heute", 1: "morgen", 2: "übermorgen", -1: "gestern", -2: "vorgestern"}
    if offset in fixed:
        return fixed[offset]
    weekday = WEEKDAYS[day.weekday()]
    if 3 <= offset <= 6:
        return f"am {weekday}"
    return f"am {weekday}, den {day.day}. {MONTHS[day.month - 1]}"


def spoken_time(value: time) -> str:
    """„6 Uhr“ / „6 Uhr 30“ (Sprachausgaben lesen „06:30“ sonst als Zahl)."""
    return f"{value.hour} Uhr" if value.minute == 0 else f"{value.hour} Uhr {value.minute}"


def _times(shift: Shift) -> str:
    if shift.start is None or shift.end is None:
        return ""
    overnight = " am nächsten Tag" if shift.end <= shift.start else ""
    return f", von {spoken_time(shift.start)} bis {spoken_time(shift.end)}{overnight}"


# ---------------------------------------------------------------------- Sätze


def describe(name: str, day: date, today: date, shift: Shift | None) -> str:
    """Ein Satz zum Dienst einer Person an einem Tag."""
    past = day < today
    when = day_phrase(day, today)
    has = "hatte" if past else "hat"
    is_ = "war" if past else "ist"
    if shift is None:
        return f"Bei {name} {is_} {when} nichts eingetragen."
    if shift.category == CAT_OFF:
        return f"{name} {has} {when} frei."
    if shift.category == CAT_VACATION:
        return f"{name} {has} {when} Urlaub."
    if shift.category == CAT_ABSENCE:
        if shift.name.casefold() in _SICK:
            return f"{name} {is_} {when} krank."
        return f"{name} {is_} {when} abwesend: {shift.name}."
    return f"{name} {has} {when} {shift.name}{_times(shift)}."


def _entry(person: Person, shift: Shift | None) -> dict:
    return {
        "name": person.name,
        "entity_id": person.entity_id,
        "code": shift.code if shift else None,
        "shift": shift.name if shift else None,
        "category": shift.category if shift else None,
        "start": shift.start.strftime("%H:%M") if shift and shift.start else None,
        "end": shift.end.strftime("%H:%M") if shift and shift.end else None,
        "hours": shift.effective_hours if shift else None,
    }


def _result(speech: str, day: date | None = None, people: list[dict] | None = None) -> dict:
    return {"speech": speech, "date": day.isoformat() if day else None, "people": people or []}


def _residue(text: str | None) -> str:
    """Text ohne Tages-, Datums- und Füllwörter: übrig bleibt der Name (oder nichts)."""
    kept = []
    for token in _tokens(text):
        folded = token.casefold().strip(".,:;!?")
        if not folded or folded in _FILLER or (_DATE_TOKEN.fullmatch(folded) and any(c.isdigit() for c in folded)):
            continue
        kept.append(token.strip(".,:;!?"))
    return " ".join(kept)


def pick_people(people: list[Person], query: str | None) -> list[Person] | None:
    """Wen die Frage meint (Name, auch inmitten eines Satzes). ``None`` = Name passt zu niemandem."""
    q = _residue(query).casefold()
    if not q or q in _EVERYONE:
        return people
    hits = [p for p in people if p.name.casefold() in q or q in p.name.casefold()]
    if hits:
        return hits
    # Nur ein Plan (z. B. „meine Frau“, „sie“): der ist gemeint; der Name steht in der Antwort
    return people if len(people) == 1 else None


def _already_over(shift: Shift, now: datetime) -> bool:
    if shift.end is None or shift.start is None or shift.end <= shift.start:
        return False  # ohne Uhrzeit oder über Mitternacht: zählt noch
    return now.time().replace(tzinfo=None) >= shift.end


def _next_work(person: Person, now: datetime) -> tuple[date, Shift] | None:
    today = now.date()
    for offset in range(LOOKAHEAD_DAYS + 1):
        day = today + timedelta(days=offset)
        shift = person.shift_on(day)
        if shift is None or shift.category != CAT_WORK:
            continue
        if offset == 0 and _already_over(shift, now):
            continue
        return day, shift
    return None


def _answer_next(selected: list[Person], now: datetime) -> dict:
    today = now.date()
    sentences: list[str] = []
    entries: list[dict] = []
    found_days: list[date] = []
    for person in selected:
        found = _next_work(person, now)
        if found is None:
            sentences.append(f"Bei {person.name} ist in den nächsten {LOOKAHEAD_DAYS} Tagen kein Dienst eingetragen.")
            entries.append(_entry(person, None))
            continue
        day, shift = found
        found_days.append(day)
        sentences.append(f"{person.name} arbeitet als Nächstes {day_phrase(day, today)}: {shift.name}{_times(shift)}.")
        entries.append(_entry(person, shift) | {"date": day.isoformat()})
    return _result(" ".join(sentences), min(found_days) if found_days else None, entries)


def answer(people: list[Person], person_query: str | None, day_text: str | None, now: datetime) -> dict:
    """Antwort auf „Wie arbeitet <Person> <Tag>?“ als ``{"speech", "date", "people"}``."""
    if not people:
        return _result("Ich finde keinen geladenen Dienstplan.")
    selected = pick_people(people, person_query)
    if selected is None:
        return _result(f"Für {_residue(person_query)} habe ich keinen Dienstplan.")
    if wants_next(day_text):
        return _answer_next(selected, now)
    today = now.date()
    day = parse_day(day_text, today)
    if day is None:
        return _result("Das Datum habe ich nicht verstanden.")
    sentences = []
    entries = []
    for person in selected:
        shift = person.shift_on(day)
        sentences.append(describe(person.name, day, today, shift))
        entries.append(_entry(person, shift))
    return _result(" ".join(sentences), day, entries)
