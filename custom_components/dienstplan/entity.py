"""Gemeinsame Hilfen für die Entitäten."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo

from .const import DOMAIN


def device_info(entry: ConfigEntry) -> DeviceInfo:
    """Ein Gerät pro Person; Kalender und Sensoren hängen daran."""
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.title,
        manufacturer="Dienstplan",
        entry_type=DeviceEntryType.SERVICE,
    )
