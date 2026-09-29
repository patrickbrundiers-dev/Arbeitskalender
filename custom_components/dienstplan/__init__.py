"""Dienstplan: Dienste pro Tag eintragen, daraus Kalendertermine erzeugen."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import hashlib
import logging
from pathlib import Path

import voluptuous as vol

from homeassistant.components import frontend as ha_frontend, panel_custom, websocket_api
from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse, callback
from homeassistant.helpers import config_validation as cv, entity_registry as er
from homeassistant.helpers.storage import Store
from homeassistant.helpers.typing import ConfigType
from homeassistant.util import dt as dt_util

from .const import (
    CARD_URL,
    DOMAIN,
    PANEL_ELEMENT,
    PANEL_ICON,
    PANEL_PATH,
    SERVICE_ASK,
    STORAGE_VERSION,
    VERSION,
    WS_GET_DAYS,
)
from .feed import DienstplanFeedView
from .manager import DienstplanManager
from .resources import UNSUPPORTED, async_ensure_resource, async_remove_resource
from .voice import Person, answer, display_name

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.CALENDAR, Platform.SENSOR]

CARD_FILE = Path(__file__).parent / "frontend" / "dienstplan-card.js"
CARD_URL_KEY = f"{DOMAIN}_card_url"

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

ASK_SCHEMA = vol.Schema(
    {
        vol.Optional("person", default=""): cv.string,
        vol.Optional("day", default="heute"): cv.string,
        vol.Optional("entity_id"): cv.entity_id,
    }
)

DienstplanConfigEntry = ConfigEntry[DienstplanManager]


@contextmanager
def _guard(step: str, report: dict[str, str] | None = None) -> Iterator[None]:
    """Einen Einrichtungsschritt absichern: Fehler werden protokolliert, die übrigen Schritte laufen weiter.

    Die Karte muss auch dann erreichbar bleiben, wenn eine Zugabe (Sprachdienst, Dashboard-Ressource,
    Seitenleiste …) an einer anderen Home-Assistant-Version scheitert.
    """
    try:
        yield
    except Exception:  # noqa: BLE001
        _LOGGER.exception("Dienstplan: Schritt „%s“ ist fehlgeschlagen; die übrigen Teile laufen weiter", step)
        if report is not None:
            report[step] = "FEHLER"


def _card_digest(path: Path) -> str | None:
    """Kurzer Fingerabdruck der Kartendatei (None, wenn sie fehlt)."""
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()[:8]
    except OSError:
        return None


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Karte ausliefern (drei voneinander unabhängige Wege), iCal-Feed, Websocket-Befehl und Service registrieren."""
    report: dict[str, str] = {}

    # Die Adresse trägt Version UND Fingerabdruck der Datei: jede Änderung ergibt eine neue Adresse, sodass
    # weder Browser- noch Service-Worker-Zwischenspeicher eine ältere Karte unter derselben Adresse ausliefern.
    digest = await hass.async_add_executor_job(_card_digest, CARD_FILE)
    card_url = f"{CARD_URL}?v={VERSION}" + (f"-{digest}" if digest else "")
    hass.data[CARD_URL_KEY] = card_url
    if digest is None:
        _LOGGER.error("Dienstplan: Kartendatei fehlt (%s). Bitte die Integration in HACS neu herunterladen", CARD_FILE)
        report["Kartendatei"] = "FEHLT"

    with _guard("Karte ausliefern", report):
        await hass.http.async_register_static_paths([StaticPathConfig(CARD_URL, str(CARD_FILE), True)])
        report["Auslieferung"] = "ok"
    # Weg 1: in jede neu geladene Startseite einbinden
    with _guard("Karte im Frontend anmelden", report):
        add_extra_js_url(hass, card_url)
        report["Frontend-Modul"] = "ok"
    # Weg 2: als Dashboard-Ressource (das Dashboard lädt sie bei jedem Öffnen selbst, unabhängig von der Startseite)
    with _guard("Dashboard-Ressource", report):
        report["Dashboard-Ressource"] = await _async_sync_dashboard_resource(hass, url=card_url)
    # Weg 3: eigene Seite in der Seitenleiste (lädt die Karte beim Öffnen selbst)
    with _guard("Seitenleiste", report):
        report["Seitenleiste"] = await _async_register_panel(hass, card_url)
    with _guard("iCal-Feed", report):
        hass.http.register_view(DienstplanFeedView(hass))
    with _guard("Websocket-Befehl", report):
        websocket_api.async_register_command(hass, ws_get_days)
    with _guard("Sprachdienst", report):
        hass.services.async_register(
            DOMAIN, SERVICE_ASK, _async_handle_ask, schema=ASK_SCHEMA, supports_response=SupportsResponse.ONLY
        )

    _LOGGER.info(
        "Dienstplan %s gestartet, Karte %s (%s)",
        VERSION,
        card_url,
        ", ".join(f"{name}: {state}" for name, state in report.items()),
    )
    return True


def _panel_exists(hass: HomeAssistant) -> bool:
    """Gibt es die Seite schon? (``async_panel_exists`` fehlt in älteren Home-Assistant-Versionen.)"""
    checker = getattr(ha_frontend, "async_panel_exists", None)
    if checker is not None:
        return bool(checker(hass, PANEL_PATH))
    return PANEL_PATH in hass.data.get("frontend_panels", {})


async def _async_register_panel(hass: HomeAssistant, card_url: str) -> str:
    """Seite „Dienstplan“ in der Seitenleiste anlegen (einmalig)."""
    if _panel_exists(hass):
        return "vorhanden"
    await panel_custom.async_register_panel(
        hass,
        frontend_url_path=PANEL_PATH,
        webcomponent_name=PANEL_ELEMENT,
        sidebar_title="Dienstplan",
        sidebar_icon=PANEL_ICON,
        module_url=card_url,
        require_admin=False,
    )
    return "ok"


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
        # Letzte Einrichtung: Dashboard-Ressource und Seitenleiste wieder aufräumen
        with _guard("Aufräumen"):
            await _async_sync_dashboard_resource(hass, url=None)
            if _panel_exists(hass):
                ha_frontend.async_remove_panel(hass, PANEL_PATH)


async def _async_sync_dashboard_resource(hass: HomeAssistant, *, url: str | None) -> str:
    """Karte als Dashboard-Ressource ein- (``url`` gesetzt) bzw. austragen (``url`` ist None).

    Ressourcen lädt das Dashboard bei jedem Öffnen selbst. Damit erscheint die Karte auch dann,
    wenn die Startseite vor dem Start dieser Integration zwischengespeichert wurde. Best effort:
    nur im Speichermodus (Standard); Fehler werden protokolliert und stören die Einrichtung nie.
    """
    try:
        resources = getattr(hass.data.get("lovelace"), "resources", None)
        if url is None:
            await async_remove_resource(resources, CARD_URL)
            return "entfernt"
        result = await async_ensure_resource(resources, CARD_URL, url)
        if result == UNSUPPORTED:
            _LOGGER.info(
                "Dienstplan: Dashboard-Ressourcen sind nicht änderbar (YAML-Modus?). Die Karte wird trotzdem "
                "ausgeliefert; im YAML-Modus bitte %s als Modul unter resources eintragen",
                url,
            )
        return result
    except Exception:  # noqa: BLE001 - die Ressource ist nur eine Zugabe
        _LOGGER.warning("Dashboard-Ressource für die Dienstplan-Karte konnte nicht angepasst werden", exc_info=True)
        return "FEHLER"


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
            "version": VERSION,
            "sync_calendar": manager.sync_calendar,
            "ical_url": manager.feed_url(),
        },
    )
