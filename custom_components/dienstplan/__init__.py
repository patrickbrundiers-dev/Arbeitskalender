"""Dienstplan: Dienste pro Tag eintragen, daraus Kalendertermine erzeugen."""

from __future__ import annotations

import logging
from pathlib import Path

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse, callback
from homeassistant.helpers import config_validation as cv, entity_registry as er
from homeassistant.helpers.storage import Store
from homeassistant.helpers.typing import ConfigType
from homeassistant.util import dt as dt_util

from .const import CARD_URL, DOMAIN, SERVICE_ASK, STORAGE_VERSION, VERSION, WS_GET_DAYS
from .feed import DienstplanFeedView
from .manager import DienstplanManager
from .resources import CREATED, UNSUPPORTED, UPDATED, async_ensure_resource, async_remove_resource
from .voice import Person, answer, display_name

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.CALENDAR, Platform.SENSOR]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

ASK_SCHEMA = vol.Schema(
    {
        vol.Optional("person", default=""): cv.string,
        vol.Optional("day", default="heute"): cv.string,
        vol.Optional("entity_id"): cv.entity_id,
    }
)

DienstplanConfigEntry = ConfigEntry[DienstplanManager]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Karte ausliefern, iCal-Feed und Websocket-Befehl registrieren (einmalig)."""
    card_path = Path(__file__).parent / "frontend" / "dienstplan-card.js"
    # Mit Cache-Header: die Adresse trägt ?v=<Version>, ein Update ändert sie und lädt die neue Karte
    await hass.http.async_register_static_paths([StaticPathConfig(CARD_URL, str(card_path), True)])
    add_extra_js_url(hass, f"{CARD_URL}?v={VERSION}")
    _LOGGER.info("Dienstplan-Karte wird unter %s bereitgestellt", CARD_URL)
    await _async_sync_dashboard_resource(hass, present=True)
    hass.http.register_view(DienstplanFeedView(hass))
    websocket_api.async_register_command(hass, ws_get_days)
    hass.services.async_register(
        DOMAIN, SERVICE_ASK, _async_handle_ask, schema=ASK_SCHEMA, supports_response=SupportsResponse.ONLY
    )
    return True


async def _async_handle_ask(call: ServiceCall) -> dict:
    """„Wie arbeitet Jenny morgen?“: fertiger deutscher Satz für Alexa, Assist oder Skripte."""
    hass = call.hass
    registry = er.async_get(hass)
    wanted = call.data.get("entity_id")
    people: list[Person] = []
    for entry in hass.config_entries.async_entries(DOMAIN):
        manager = getattr(entry, "runtime_data", None)
        if manager is None or entry.state is not ConfigEntryState.LOADED:
            continue
        entity_id = registry.async_get_entity_id("calendar", DOMAIN, entry.entry_id)
        if wanted and entity_id != wanted:
            continue
        people.append(Person(display_name(entry.title), entity_id, manager.shift_on))
    return answer(people, call.data.get("person", ""), call.data.get("day", "heute"), dt_util.now())


async def async_setup_entry(hass: HomeAssistant, entry: DienstplanConfigEntry) -> bool:
    """Eintrag einrichten."""
    manager = DienstplanManager(hass, entry)
    await manager.async_load()
    entry.runtime_data = manager

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: DienstplanConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: DienstplanConfigEntry) -> None:
    """Gespeicherte Dienste löschen, wenn der Eintrag entfernt wird."""
    await Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}").async_remove()
    if not [e for e in hass.config_entries.async_entries(DOMAIN) if e.entry_id != entry.entry_id]:
        await _async_sync_dashboard_resource(hass, present=False)  # letzte Einrichtung: Ressource aufräumen


async def _async_sync_dashboard_resource(hass: HomeAssistant, *, present: bool) -> None:
    """Karte als Dashboard-Ressource ein- bzw. austragen.

    Ressourcen lädt das Dashboard bei jedem Öffnen selbst. Damit erscheint die Karte auch dann,
    wenn die Seite vor dem Start dieser Integration geladen wurde. Best effort: nur im
    Speichermodus (Standard), Fehler werden nur protokolliert und stören die Einrichtung nie.
    """
    try:
        resources = getattr(hass.data.get("lovelace"), "resources", None)
        if present:
            result = await async_ensure_resource(resources, CARD_URL, f"{CARD_URL}?v={VERSION}")
            if result in (CREATED, UPDATED):
                _LOGGER.info("Dienstplan-Karte als Dashboard-Ressource eingetragen (%s)", result)
            elif result == UNSUPPORTED:
                _LOGGER.debug("Dashboard-Ressourcen nicht änderbar (YAML-Modus?) – Karte wird trotzdem ausgeliefert")
        else:
            await async_remove_resource(resources, CARD_URL)
    except Exception:  # noqa: BLE001 - die Ressource ist nur eine Zugabe
        _LOGGER.warning("Dashboard-Ressource für die Dienstplan-Karte konnte nicht angepasst werden", exc_info=True)


async def _async_options_updated(hass: HomeAssistant, entry: DienstplanConfigEntry) -> None:
    """Nach Änderung der Optionen neu laden und geänderte Termine abgleichen."""
    await hass.config_entries.async_reload(entry.entry_id)
    manager = getattr(entry, "runtime_data", None)
    if manager is not None and entry.state is ConfigEntryState.LOADED and manager.sync_calendar:
        entry.async_create_background_task(hass, manager.async_sync(), f"{DOMAIN}_resync_{entry.entry_id}")


@websocket_api.websocket_command(
    {
        vol.Required("type"): WS_GET_DAYS,
        vol.Required("entity_id"): cv.entity_id,
        vol.Required("start"): cv.date,
        vol.Required("end"): cv.date,
    }
)
@callback
def ws_get_days(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    """Dienste, Dienstdefinitionen und Wochenstunden für die Karte liefern."""
    registry_entry = er.async_get(hass).async_get(msg["entity_id"])
    config_entry = (
        hass.config_entries.async_get_entry(registry_entry.config_entry_id)
        if registry_entry is not None and registry_entry.platform == DOMAIN and registry_entry.config_entry_id
        else None
    )
    if config_entry is None or config_entry.state is not ConfigEntryState.LOADED:
        connection.send_error(msg["id"], websocket_api.ERR_NOT_FOUND, "Dienstplan-Kalender nicht gefunden")
        return

    manager: DienstplanManager = config_entry.runtime_data
    connection.send_result(
        msg["id"],
        {
            "shifts": [shift.as_dict() for shift in manager.shifts.values()],
            "days": manager.days_between(msg["start"], msg["end"]),
            "weeks": manager.stats_range(msg["start"], msg["end"]),
            "sync_calendar": manager.sync_calendar,
            "ical_url": manager.feed_url(),
        },
    )
