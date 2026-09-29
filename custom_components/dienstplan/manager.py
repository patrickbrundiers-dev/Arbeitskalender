"""Verwaltung der Dienste: Speicherung, Termine und Abgleich in einen Ziel-Kalender."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, time, timedelta
import logging

import voluptuous as vol

from homeassistant.components import persistent_notification
from homeassistant.components.calendar import CalendarEntityFeature, CalendarEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    CONF_SHIFTS,
    CONF_SYNC_CALENDAR,
    DOMAIN,
    EVENT_LOOKAHEAD_DAYS,
    STORAGE_VERSION,
)
from .shifts import (
    DEFAULT_SHIFTS_TEXT,
    Shift,
    ShiftParseError,
    event_bounds,
    find_shift,
    parse_shifts,
)

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
        self.synced: dict[str, str] = {}
        self._listeners: list[Callable[[], None]] = []

        text = entry.options.get(CONF_SHIFTS, entry.data.get(CONF_SHIFTS, DEFAULT_SHIFTS_TEXT))
        try:
            self.shifts = parse_shifts(text)
        except ShiftParseError as err:
            _LOGGER.error("Dienstdefinition ungültig (%s) – verwende Standardwerte", err)
            self.shifts = parse_shifts(DEFAULT_SHIFTS_TEXT)

    # ------------------------------------------------------------------ Konfiguration

    @property
    def sync_calendar(self) -> str | None:
        """Ziel-Kalender für den Abgleich (oder ``None``)."""
        value = self.entry.options.get(CONF_SYNC_CALENDAR, self.entry.data.get(CONF_SYNC_CALENDAR))
        return value or None

    # ------------------------------------------------------------------ Speicherung

    async def async_load(self) -> None:
        data = await self.store.async_load() or {}
        self.days = {k: v for k, v in data.get("days", {}).items() if isinstance(v, str) and v}
        self.synced = {k: v for k, v in data.get("synced", {}).items() if isinstance(v, str) and v}

    async def _async_save(self) -> None:
        await self.store.async_save({"days": self.days, "synced": self.synced})

    async def async_remove_storage(self) -> None:
        await self.store.async_remove()

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

    async def async_sync(self, only: set[str] | None = None) -> None:
        """Termine im Ziel-Kalender anlegen bzw. ersetzen.

        Es werden nur Tage angefasst, bei denen sich der Dienst seit dem letzten
        Abgleich geändert hat.
        """
        target = self.sync_calendar
        if not target:
            return

        keys = only if only is not None else set(self.days) | set(self.synced)
        manual_cleanup: list[str] = []
        failed: list[str] = []
        dirty = False

        for key in sorted(keys):
            shift = find_shift(self.shifts, self.days.get(key))
            desired = shift.code if shift is not None and shift.creates_event else None
            current = self.synced.get(key)
            if desired == current:
                continue

            day = date.fromisoformat(key)
            if current is not None:
                if not await self._async_delete_remote(target, day):
                    manual_cleanup.append(f"{day.strftime('%d.%m.%Y')} ({current})")
                self.synced.pop(key, None)
                dirty = True

            if desired is not None and shift is not None:
                if await self._async_create_remote(target, day, shift):
                    self.synced[key] = desired
                    dirty = True
                else:
                    failed.append(f"{day.strftime('%d.%m.%Y')} ({desired})")

        if dirty:
            await self._async_save()

        if manual_cleanup or failed:
            lines = []
            if manual_cleanup:
                lines.append(
                    f"Alte Termine in **{target}** konnten nicht automatisch entfernt werden "
                    "(Kalender unterstützt kein Löschen). Bitte manuell löschen: "
                    + ", ".join(manual_cleanup)
                )
            if failed:
                lines.append(
                    f"Folgende Termine konnten nicht in **{target}** angelegt werden "
                    "(Details im Log; Service „Dienstplan: Abgleichen“ wiederholt den Versuch): "
                    + ", ".join(failed)
                )
            persistent_notification.async_create(
                self.hass,
                "\n\n".join(lines),
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
