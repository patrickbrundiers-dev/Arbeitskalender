"""Sensoren des Dienstplans: Dienst heute/morgen, nächster Beginn, Stunden, Urlaub."""

from __future__ import annotations

from datetime import datetime, timedelta

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from . import DienstplanConfigEntry
from .entity import device_info
from .manager import DienstplanManager
from .shifts import event_bounds
from .stats import week_start

SCAN_INTERVAL = timedelta(minutes=1)
NO_SHIFT = "Kein Dienst"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DienstplanConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    manager = entry.runtime_data
    entities: list[DienstplanSensor] = [
        ShiftDaySensor(entry, "shift_today", 0),
        ShiftDaySensor(entry, "shift_tomorrow", 1),
        NextShiftSensor(entry),
        WeekHoursSensor(entry),
        VacationTakenSensor(entry),
    ]
    if manager.weekly_hours > 0:
        entities.append(WeekBalanceSensor(entry))
    if manager.vacation_days > 0:
        entities.append(VacationLeftSensor(entry))
    async_add_entities(entities)


class DienstplanSensor(SensorEntity):
    """Basis: hängt am Gerät der Person und aktualisiert sich bei Änderungen."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, entry: DienstplanConfigEntry, key: str) -> None:
        self.manager: DienstplanManager = entry.runtime_data
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = device_info(entry)

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.manager.async_add_listener(self.async_write_ha_state))


class ShiftDaySensor(DienstplanSensor):
    """Dienst an einem Tag (heute/morgen)."""

    def __init__(self, entry: DienstplanConfigEntry, key: str, offset: int) -> None:
        super().__init__(entry, key)
        self._offset = offset

    def _shift(self):
        return self.manager.shift_on(dt_util.now().date() + timedelta(days=self._offset))

    @property
    def native_value(self) -> str:
        shift = self._shift()
        return shift.name if shift else NO_SHIFT

    @property
    def extra_state_attributes(self) -> dict:
        shift = self._shift()
        if shift is None:
            return {"code": None, "start": None, "end": None, "hours": None}
        data = shift.as_dict()
        return {k: data[k] for k in ("code", "start", "end", "hours")}


class NextShiftSensor(DienstplanSensor):
    """Beginn des nächsten Dienstes (für Wecker/Erinnerungen)."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, entry: DienstplanConfigEntry) -> None:
        super().__init__(entry, "next_shift_start")

    @property
    def native_value(self) -> datetime | None:
        result = self.manager.next_work_start()
        return result[0] if result else None

    @property
    def extra_state_attributes(self) -> dict:
        result = self.manager.next_work_start()
        if result is None:
            return {"code": None, "name": None, "end": None}
        start, shift = result
        bounds = event_bounds(shift, start.date(), dt_util.get_default_time_zone())
        return {
            "code": shift.code,
            "name": shift.name,
            "end": bounds[1].isoformat() if bounds else None,
        }


class WeekHoursSensor(DienstplanSensor):
    """Stunden der laufenden Woche."""

    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.HOURS
    _attr_suggested_display_precision = 2

    def __init__(self, entry: DienstplanConfigEntry) -> None:
        super().__init__(entry, "hours_week")

    @property
    def native_value(self) -> float:
        return self.manager.current_week_stats()["hours"]

    @property
    def extra_state_attributes(self) -> dict:
        stats = self.manager.current_week_stats()
        return {
            "week_start": week_start(dt_util.now().date()).isoformat(),
            "target": stats["target"],
            "balance": stats["balance"],
            "shifts_without_hours": stats["missing"],
        }


class WeekBalanceSensor(DienstplanSensor):
    """Wochenbilanz (Ist minus Soll); nur mit angegebenem Wochensoll."""

    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.HOURS
    _attr_suggested_display_precision = 2

    def __init__(self, entry: DienstplanConfigEntry) -> None:
        super().__init__(entry, "balance_week")

    @property
    def native_value(self) -> float | None:
        return self.manager.current_week_stats()["balance"]


class VacationTakenSensor(DienstplanSensor):
    """Urlaubstage (Mo–Fr) dieses Jahres."""

    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.DAYS

    def __init__(self, entry: DienstplanConfigEntry) -> None:
        super().__init__(entry, "vacation_taken")

    @property
    def native_value(self) -> int:
        return self.manager.vacation_taken(dt_util.now().year)

    @property
    def extra_state_attributes(self) -> dict:
        return {"year": dt_util.now().year}


class VacationLeftSensor(DienstplanSensor):
    """Resturlaub; nur mit angegebenem Jahresurlaub."""

    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.DAYS

    def __init__(self, entry: DienstplanConfigEntry) -> None:
        super().__init__(entry, "vacation_left")

    @property
    def native_value(self) -> int | None:
        return self.manager.vacation_left(dt_util.now().year)

    @property
    def extra_state_attributes(self) -> dict:
        return {"year": dt_util.now().year, "total": self.manager.vacation_days}
