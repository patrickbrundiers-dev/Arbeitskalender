"""Kalender-Entität des Dienstplans."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import voluptuous as vol

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv, entity_platform
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from . import DienstplanConfigEntry
from .const import DOMAIN, SERVICE_REGENERATE_LINK, SERVICE_SET_SHIFT, SERVICE_SET_SHIFTS, SERVICE_SYNC
from .entity import device_info
from .manager import DienstplanManager

SCAN_INTERVAL = timedelta(minutes=1)
MAX_RANGE_DAYS = 366


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DienstplanConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Kalender und Services einrichten."""
    async_add_entities([DienstplanCalendar(entry)])

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        SERVICE_SET_SHIFT,
        {
            vol.Required("date"): cv.date,
            vol.Optional("end_date"): cv.date,
            vol.Optional("shift", default=""): cv.string,
        },
        "async_set_shift",
    )
    platform.async_register_entity_service(
        SERVICE_SET_SHIFTS,
        {vol.Required("days"): {cv.date: vol.Any(None, cv.string)}},
        "async_set_shifts",
    )
    platform.async_register_entity_service(SERVICE_SYNC, None, "async_sync_now")
    platform.async_register_entity_service(SERVICE_REGENERATE_LINK, None, "async_regenerate_link")


class DienstplanCalendar(CalendarEntity):
    """Kalender mit den eingetragenen Diensten einer Person."""

    _attr_has_entity_name = True
    _attr_name = "Dienstplan"
    _attr_should_poll = True
    # Der Link enthält den geheimen Token: nicht in der Datenbank/im Verlauf speichern
    _unrecorded_attributes = frozenset({"ical_url"})

    def __init__(self, entry: DienstplanConfigEntry) -> None:
        self.manager: DienstplanManager = entry.runtime_data
        self._attr_unique_id = entry.entry_id
        self._attr_device_info = device_info(entry)

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.manager.async_add_listener(self.async_write_ha_state))

    @property
    def event(self) -> CalendarEvent | None:
        """Aktueller oder nächster Dienst."""
        return self.manager.current_or_next_event()

    @property
    def extra_state_attributes(self) -> dict:
        today = dt_util.now().date()
        attrs: dict = {}
        for label, day in (("today", today), ("tomorrow", today + timedelta(days=1))):
            shift = self.manager.shift_on(day)
            attrs[f"{label}_shift"] = shift.code if shift else None
            attrs[f"{label}_shift_name"] = shift.name if shift else None
        attrs["sync_calendar"] = self.manager.sync_calendar
        attrs["ical_url"] = self.manager.feed_url()
        return attrs

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        return self.manager.events_between(start_date, end_date)

    # ------------------------------------------------------------------ Services

    async def async_set_shift(self, date: date, shift: str = "", end_date: date | None = None) -> None:
        """Dienst für einen Tag oder Zeitraum setzen (leer = löschen)."""
        last = end_date or date
        days = (last - date).days
        if days < 0 or days > MAX_RANGE_DAYS:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="invalid_range")
        await self.manager.async_set_days({date + timedelta(days=i): shift for i in range(days + 1)})

    async def async_set_shifts(self, days: dict[date, str | None]) -> None:
        """Mehrere Tage auf einmal setzen (so speichert die Karte)."""
        await self.manager.async_set_days(days)

    async def async_sync_now(self) -> None:
        """Alle Tage mit dem Ziel-Kalender abgleichen."""
        await self.manager.async_sync()

    async def async_regenerate_link(self) -> None:
        """Neuen iCal-Link erzeugen (der alte wird ungültig)."""
        await self.manager.async_regenerate_token()
