"""Stunden-, Bilanz- und Urlaubsberechnung (ohne Home-Assistant-Abhängigkeiten)."""

from __future__ import annotations

from datetime import date, timedelta

from .shifts import CAT_ABSENCE, CAT_VACATION, CAT_WORK, Shift, find_shift


def week_start(day: date) -> date:
    """Montag der Woche."""
    return day - timedelta(days=day.weekday())


def week_stats(
    days: dict[str, str],
    shifts: dict[str, Shift],
    monday: date,
    weekly_target: float = 0.0,
) -> dict:
    """Stunden einer Woche (Mo–So).

    * Dienste zählen mit ihren Stunden (Nachtdienst am Tag des Beginns).
    * Urlaub/Abwesenheit an Werktagen (Mo–Fr) wird mit Soll/5 gutgeschrieben,
      wenn ein Wochensoll angegeben ist.
    * ``missing`` zählt Dienste ohne bekannte Stunden.
    """
    hours = 0.0
    missing = 0
    credit = weekly_target / 5 if weekly_target > 0 else 0.0
    for offset in range(7):
        day = monday + timedelta(days=offset)
        shift = find_shift(shifts, days.get(day.isoformat()))
        if shift is None:
            continue
        if shift.category == CAT_WORK:
            worked = shift.effective_hours
            if worked is None:
                missing += 1
            else:
                hours += worked
        elif shift.category in (CAT_ABSENCE, CAT_VACATION) and day.weekday() < 5:
            hours += credit
    target = weekly_target if weekly_target > 0 else None
    return {
        "hours": round(hours, 2),
        "target": target,
        "balance": round(hours - weekly_target, 2) if target is not None else None,
        "missing": missing,
    }


def stats_for_range(
    days: dict[str, str],
    shifts: dict[str, Shift],
    start: date,
    end: date,
    weekly_target: float = 0.0,
) -> dict[str, dict]:
    """Wochenstatistik für alle Wochen zwischen ``start`` und ``end`` (Schlüssel = Montag)."""
    result: dict[str, dict] = {}
    monday = week_start(start)
    while monday <= end:
        result[monday.isoformat()] = week_stats(days, shifts, monday, weekly_target)
        monday += timedelta(days=7)
    return result


def vacation_days_taken(days: dict[str, str], shifts: dict[str, Shift], year: int) -> int:
    """Urlaubstage (Mo–Fr) eines Jahres."""
    count = 0
    prefix = f"{year:04d}-"
    for key, code in days.items():
        if not key.startswith(prefix):
            continue
        shift = find_shift(shifts, code)
        if shift is not None and shift.category == CAT_VACATION and date.fromisoformat(key).weekday() < 5:
            count += 1
    return count
