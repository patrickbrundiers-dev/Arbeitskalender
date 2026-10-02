"""Verwaltung der Dienste: Speicherung, Termine, Statistik, Feed und Abgleich in einen Ziel-Kalender."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, time, timedelta
import asyncio
import logging
import secrets

import voluptuous as vol

from homeassistant.components import persistent_notification
from homeassistant.components.calendar import CalendarEntityFeature, CalendarEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.network import NoURLAvailableError, get_url
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    CONF_SHIFTS,
    CONF_SYNC_CALENDAR,
    CONF_VACATION_DAYS,
    CONF_WEEKLY_HOURS,
    DOMAIN,
    EVENT_LOOKAHEAD_DAYS,
    FEED_DAYS_AHEAD,
    FEED_DAYS_BACK,
    STORAGE_RETENTION_DAYS,
    STORAGE_VERSION,
    SYNC_DAYS_BACK,
)
from .ical import IcsEvent, build_ics
from .shifts import (
    CAT_WORK,
    DEFAULT_SHIFTS_TEXT,
    KIND_TIMED,
    Shift,
    ShiftParseError,
    event_bounds,
    find_shift,
    parse_shifts,
)
from .stats import stats_for_range, vacation_days_taken, week_start, week_stats

_LOGGER = logging.getLogger(__name__)


def _as_datetime(value: date | datetime, tz) -> datetime:
    """Ganztags-Datum oder Zeitpunkt als zeitzonenbehaftete datetime."""
    if isinstance(value, datetime):
        return value
    return datetime.combine(value, time.min, tzinfo=tz)


class DienstplanManager:
    """Hält die eingetragenen Dienste einer Person."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.store: Store[dict] = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}")
        self.days: dict[str, str] = {}
        self.synced: dict[str, str] = {}  # Datum -> Signatur des übertragenen Termins
        self.synced_target: str | None = None
        self.token: str = ""
        self._listeners: list[Callable[[], None]] = []
        self._sync_lock = asyncio.Lock()

        text = self._opt(CONF_SHIFTS, DEFAULT_SHIFTS_TEXT)
        try:
            self.shifts = parse_shifts(text)
        except ShiftParseError as err:
            _LOGGER.error("Dienstdefinition ungültig (%s) – verwende Standardwerte", err)
            self.shifts = parse_shifts(DEFAULT_SHIFTS_TEXT)

    # ------------------------------------------------------------------ Konfiguration

    def _opt(self, key: str, default=None):
        return self.entry.options.get(key, self.entry.data.get(key, default))

    @property
    def sync_calendar(self) -> str | None:
        """Ziel-Kalender für den Abgleich (oder ``None``)."""
        return self._opt(CONF_SYNC_CALENDAR) or None

    @property
    def weekly_hours(self) -> float:
        try:
            return max(0.0, float(self._opt(CONF_WEEKLY_HOURS, 0) or 0))
        except (TypeError, ValueError):
            return 0.0

    @property
    def vacation_days(self) -> int:
        try:
            return max(0, int(float(self._opt(CONF_VACATION_DAYS, 0) or 0)))
        except (TypeError, ValueError):
            return 0

    # ------------------------------------------------------------------ Speicherung

    async def async_load(self) -> None:
        data = await self.store.async_load() or {}
        self.days = {k: v for k, v in data.get("days", {}).items() if isinstance(v, str) and v}
        self.synced = {k: v for k, v in data.get("synced", {}).items() if isinstance(v, str) and v}
        self.synced_target = data.get("synced_target") or None
        self.token = data.get("token") or ""
        if not self.token:
            self.token = secrets.token_urlsafe(24)
            await self._async_save()

    async def _async_save(self) -> None:
        await self.store.async_save(
            {
                "days": self.days,
                "synced": self.synced,
                "synced_target": self.synced_target,
                "token": self.token,
            }
        )

    async def async_prune_storage(self) -> None:
        """Begrenzt alte aktive Diensttage auf den Feed-Zeitraum."""
        cutoff = dt_util.now().date() - timedelta(days=STORAGE_RETENTION_DAYS)
        changed = False
        for key in list(self.days):
            try:
                if date.fromisoformat(key) < cutoff:
                    self.days.pop(key, None)
                    changed = True
            except ValueError:
                self.days.pop(key, None)
                changed = True
        if changed:
            await self._async_save()

    # ------------------------------------------------------------------ Listener

    @callback
    def async_add_listener(self, update_callback: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(update_callback)

        @callback
        def remove() -> None:
            if update_callback in self._listeners:
                self._listeners.remove(update_callback)

        return remove

    @callback
    def _notify(self) -> None:
        for update_callback in list(self._listeners):
            update_callback()

    # ------------------------------------------------------------------ Abfragen

    def shift_on(self, day: date) -> Shift | None:
        return find_shift(self.shifts, self.days.get(day.isoformat()))

    def days_between(self, start: date, end: date) -> dict[str, str]:
        lo, hi = start.isoformat(), end.isoformat()
        return {k: v for k, v in self.days.items() if lo <= k <= hi}

    def _marker(self, day: date) -> str:
        return f"[dienstplan:{self.entry.entry_id}:{day.isoformat()}]"

    def _event_for(self, day: date, shift: Shift) -> CalendarEvent | None:
        bounds = event_bounds(shift, day, dt_util.get_default_time_zone())
        if bounds is None:
            return None
        start, end = bounds
        return CalendarEvent(
            start=start,
            end=end,
            summary=shift.name,
            description=f"Kürzel: {shift.code}",
            uid=f"{self.entry.entry_id}-{day.isoformat()}",
        )

    def events_between(self, start: datetime, end: datetime) -> list[CalendarEvent]:
        """Alle Termine, die sich mit dem Zeitraum überschneiden."""
        tz = dt_util.get_default_time_zone()
        first = (dt_util.as_local(start).date() - timedelta(days=1)).isoformat()
        last = dt_util.as_local(end).date().isoformat()
        events: list[CalendarEvent] = []
        for key in sorted(self.days):
            if key < first or key > last:
                continue
            day = date.fromisoformat(key)
            shift = find_shift(self.shifts, self.days[key])
            if shift is None:
                continue
            event = self._event_for(day, shift)
            if event is None:
                continue
            if _as_datetime(event.start, tz) < end and _as_datetime(event.end, tz) > start:
                events.append(event)
        return events

    def current_or_next_event(self) -> CalendarEvent | None:
        now = dt_util.now()
        tz = dt_util.get_default_time_zone()
        events = self.events_between(now, now + timedelta(days=EVENT_LOOKAHEAD_DAYS))
        events.sort(key=lambda event: _as_datetime(event.start, tz))
        return events[0] if events else None

    def next_work_start(self) -> tuple[datetime, Shift] | None:
        """Beginn des nächsten Dienstes mit bekannter Uhrzeit."""
        now = dt_util.now()
        tz = dt_util.get_default_time_zone()
        earliest = (now.date() - timedelta(days=1)).isoformat()
        for key in sorted(self.days):
            if key < earliest:
                continue
            shift = find_shift(self.shifts, self.days[key])
            if shift is None or shift.category != CAT_WORK or shift.kind != KIND_TIMED or shift.start is None:
                continue
            start = datetime.combine(date.fromisoformat(key), shift.start, tzinfo=tz)
            if start > now:
                return start, shift
        return None

    # ------------------------------------------------------------------ Statistik

    def week_stats(self, monday: date) -> dict:
        return week_stats(self.days, self.shifts, monday, self.weekly_hours)

    def current_week_stats(self) -> dict:
        return self.week_stats(week_start(dt_util.now().date()))

    def stats_range(self, start: date, end: date) -> dict[str, dict]:
        return stats_for_range(self.days, self.shifts, start, end, self.weekly_hours)

    def vacation_taken(self, year: int) -> int:
        return vacation_days_taken(self.days, self.shifts, year)

    def vacation_left(self, year: int) -> int | None:
        total = self.vacation_days
        return total - self.vacation_taken(year) if total > 0 else None

    # ------------------------------------------------------------------ iCal-Feed

    def feed_path(self) -> str:
        return f"/api/{DOMAIN}/feed/{self.entry.entry_id}/{self.token}/calendar.ics"

    def feed_url(self) -> str:
        path = self.feed_path()
        try:
            return f"{get_url(self.hass, prefer_external=True)}{path}"
        except NoURLAvailableError:
            return path

    def build_feed(self) -> str:
        today = dt_util.now().date()
        lo = (today - timedelta(days=FEED_DAYS_BACK)).isoformat()
        hi = (today + timedelta(days=FEED_DAYS_AHEAD)).isoformat()
        tz = dt_util.get_default_time_zone()
        events: list[IcsEvent] = []
        for key in sorted(self.days):
            if key < lo or key > hi:
                continue
            day = date.fromisoformat(key)
            shift = find_shift(self.shifts, self.days[key])
            bounds = event_bounds(shift, day, tz) if shift is not None else None
            if shift is None or bounds is None:
                continue
            events.append(
                IcsEvent(
                    uid=f"{self.entry.entry_id}-{key}@dienstplan",
                    summary=shift.name,
                    start=bounds[0],
                    end=bounds[1],
                    description=f"Kürzel: {shift.code}",
                )
            )
        return build_ics(self.entry.title, events, dt_util.utcnow())

    async def async_regenerate_token(self) -> None:
        """Neuen Feed-Link erzeugen; der alte Link funktioniert danach nicht mehr."""
        self.token = secrets.token_urlsafe(24)
        await self._async_save()
        self._notify()

    # ------------------------------------------------------------------ Ändern

    async def async_set_days(self, changes: dict[date, str | None]) -> None:
        """Dienste für mehrere Tage setzen (leer/None = Eintrag löschen)."""
        normalized: dict[str, str | None] = {}
        for day, code in changes.items():
            if not code:
                normalized[day.isoformat()] = None
                continue
            shift = find_shift(self.shifts, code)
            if shift is None:
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="unknown_shift",
                    translation_placeholders={"shift": str(code)},
                )
            normalized[day.isoformat()] = shift.code

        changed: set[str] = set()
        for key, code in normalized.items():
            if code is None:
                if self.days.pop(key, None) is not None:
                    changed.add(key)
            elif self.days.get(key) != code:
                self.days[key] = code
                changed.add(key)

        if not changed:
            return
        await self._async_save()
        self._notify()
        await self.async_sync(changed)

    # ------------------------------------------------------------------ Abgleich

    async def _async_delete_all_owned(self, target: str) -> bool:
        """Entfernt alle von diesem Dienstplan erzeugten Termine aus einem Kalender."""
        component = self.hass.data.get("calendar")
        entity = component.get_entity(target) if component is not None else None
        if entity is None or not (entity.supported_features & CalendarEntityFeature.DELETE_EVENT):
            return False
        tz = dt_util.get_default_time_zone()
        start = datetime.combine(dt_util.now().date() - timedelta(days=STORAGE_RETENTION_DAYS), time.min, tzinfo=tz)
        end = datetime.combine(dt_util.now().date() + timedelta(days=FEED_DAYS_AHEAD), time.min, tzinfo=tz)
        prefix = f"[dienstplan:{self.entry.entry_id}:"
        try:
            events = await entity.async_get_events(self.hass, start, end)
            for event in events:
                if event.uid and prefix in (event.description or ""):
                    await entity.async_delete_event(event.uid)
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Dienstplan-Termine in %s konnten nicht vollständig bereinigt werden: %s", target, err)
            return False
        return True

    async def async_sync(self, only: set[str] | None = None) -> None:
        """Synchronisiert Dienstplan-Termine seriell und wiederholbar."""
        async with self._sync_lock:
            target = self.sync_calendar
            old_target = self.synced_target

            if target != old_target:
                if old_target and not await self._async_delete_all_owned(old_target):
                    persistent_notification.async_create(
                        self.hass,
                        f"Der alte Dienstplan-Kalender **{old_target}** konnte nicht vollständig bereinigt werden. "
                        "Der Zielkalender wurde noch nicht umgestellt.",
                        title=f"Dienstplan {self.entry.title}",
                        notification_id=f"{DOMAIN}_{self.entry.entry_id}_sync",
                    )
                    return
                self.synced.clear()
                self.synced_target = target
                await self._async_save()

            if not target:
                return

            if only is None:
                cutoff = (dt_util.now().date() - timedelta(days=SYNC_DAYS_BACK)).isoformat()
                keys = {k for k in set(self.days) | set(self.synced) if k >= cutoff}
            else:
                keys = set(only)

            manual_cleanup: list[str] = []
            failed: list[str] = []
            for key in sorted(keys):
                shift = find_shift(self.shifts, self.days.get(key))
                desired = shift.signature() if shift is not None and shift.creates_event else None
                current = self.synced.get(key)
                if desired == current:
                    continue
                day = date.fromisoformat(key)

                if current is not None:
                    if not await self._async_delete_remote(target, day):
                        manual_cleanup.append(f"{day.strftime('%d.%m.%Y')} ({current.split('|')[0]})")
                        continue
                    self.synced.pop(key, None)
                    await self._async_save()

                if desired is not None and shift is not None:
                    if await self._async_create_remote(target, day, shift):
                        self.synced[key] = desired
                        await self._async_save()
                    else:
                        failed.append(f"{day.strftime('%d.%m.%Y')} ({shift.code})")

            if manual_cleanup or failed:
                lines = []
                if manual_cleanup:
                    lines.append("Termine konnten nicht automatisch entfernt werden: " + ", ".join(manual_cleanup))
                if failed:
                    lines.append("Termine konnten nicht angelegt werden: " + ", ".join(failed))
                persistent_notification.async_create(
                    self.hass,
                    "

".join(lines) + "

Der nächste Dienstplan-Abgleich wiederholt fehlgeschlagene Schritte.",
                    title=f"Dienstplan {self.entry.title}",
                    notification_id=f"{DOMAIN}_{self.entry.entry_id}_sync",
                )

    async def _async_create_remote(self, target: str, day: date, shift: Shift) -> bool:
        bounds = event_bounds(shift, day, dt_util.get_default_time_zone())
        if bounds is None:
            return True
        start, end = bounds
        data: dict = {
            "entity_id": target,
            "summary": shift.name,
            "description": f"Dienstplan-Eintrag {shift.code} {self._marker(day)}",
        }
        if isinstance(start, datetime):
            data["start_date_time"] = start.isoformat()
            data["end_date_time"] = end.isoformat()
        else:
            data["start_date"] = start.isoformat()
            data["end_date"] = end.isoformat()
        try:
            await self.hass.services.async_call("calendar", "create_event", data, blocking=True)
        except (HomeAssistantError, vol.Invalid) as err:
            _LOGGER.warning("Termin %s in %s nicht angelegt: %s", day, target, err)
            return False
        return True

    async def _async_delete_remote(self, target: str, day: date) -> bool:
        """Früher angelegten Termin entfernen (nur wenn der Ziel-Kalender das kann)."""
        component = self.hass.data.get("calendar")
        entity = component.get_entity(target) if component is not None else None
        if entity is None or not (entity.supported_features & CalendarEntityFeature.DELETE_EVENT):
            return False

        tz = dt_util.get_default_time_zone()
        start = datetime.combine(day, time.min, tzinfo=tz)
        end = datetime.combine(day + timedelta(days=2), time.min, tzinfo=tz)
        marker = self._marker(day)
        try:
            events = await entity.async_get_events(self.hass, start, end)
            for event in events:
                if event.uid and marker in (event.description or ""):
                    await entity.async_delete_event(event.uid)
        except Exception as err:  # noqa: BLE001 - best effort, Ziel-Kalender ist fremd
            _LOGGER.warning("Alter Termin vom %s in %s nicht gelöscht: %s", day, target, err)
            return False
        return True
