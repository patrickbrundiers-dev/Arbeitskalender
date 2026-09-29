"""Einrichtung und Optionen des Dienstplans."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    TextSelector,
    TextSelectorConfig,
)

from .const import CONF_NAME, CONF_SHIFTS, CONF_SYNC_CALENDAR, DOMAIN
from .shifts import DEFAULT_SHIFTS_TEXT, ShiftParseError, parse_shifts

_LOGGER = logging.getLogger(__name__)

_SHIFTS_SELECTOR = TextSelector(TextSelectorConfig(multiline=True))
_CALENDAR_SELECTOR = EntitySelector(EntitySelectorConfig(domain="calendar"))


def _validate(hass: HomeAssistant, user_input: dict[str, Any]) -> tuple[dict[str, str], str]:
    """Eingaben prüfen. Gibt (Fehler, Klartext-Fehlerhinweis) zurück."""
    errors: dict[str, str] = {}
    detail = ""

    try:
        if not parse_shifts(user_input[CONF_SHIFTS]):
            errors[CONF_SHIFTS] = "no_shifts"
    except ShiftParseError as err:
        errors[CONF_SHIFTS] = "invalid_shifts"
        detail = f"⚠️ {err}"
        _LOGGER.debug("Ungültige Dienstdefinition: %s", err)

    target = user_input.get(CONF_SYNC_CALENDAR)
    if target:
        registry_entry = er.async_get(hass).async_get(target)
        if registry_entry is not None and registry_entry.platform == DOMAIN:
            errors[CONF_SYNC_CALENDAR] = "sync_self"

    return errors, detail


class DienstplanConfigFlow(ConfigFlow, domain=DOMAIN):
    """Neue Person / neuen Dienstplan anlegen."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return DienstplanOptionsFlow()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        detail = ""
        if user_input is not None:
            errors, detail = _validate(self.hass, user_input)
            if not errors:
                return self.async_create_entry(
                    title=user_input[CONF_NAME].strip() or "Dienstplan",
                    data={
                        CONF_SHIFTS: user_input[CONF_SHIFTS],
                        CONF_SYNC_CALENDAR: user_input.get(CONF_SYNC_CALENDAR) or "",
                    },
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_NAME): str,
                vol.Required(CONF_SHIFTS): _SHIFTS_SELECTOR,
                vol.Optional(CONF_SYNC_CALENDAR): _CALENDAR_SELECTOR,
            }
        )
        suggested = user_input or {CONF_NAME: "Dienstplan", CONF_SHIFTS: DEFAULT_SHIFTS_TEXT}
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(schema, suggested),
            errors=errors,
            description_placeholders={"error": detail},
        )


class DienstplanOptionsFlow(OptionsFlow):
    """Dienste und Ziel-Kalender nachträglich ändern."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        detail = ""
        if user_input is not None:
            errors, detail = _validate(self.hass, user_input)
            if not errors:
                # Leer speichern, damit ein entfernter Ziel-Kalender nicht auf den
                # ursprünglichen Wert zurückfällt.
                user_input.setdefault(CONF_SYNC_CALENDAR, "")
                return self.async_create_entry(data=user_input)

        entry = self.config_entry
        current = user_input or {
            CONF_SHIFTS: entry.options.get(CONF_SHIFTS, entry.data.get(CONF_SHIFTS, DEFAULT_SHIFTS_TEXT)),
            CONF_SYNC_CALENDAR: entry.options.get(CONF_SYNC_CALENDAR, entry.data.get(CONF_SYNC_CALENDAR)) or None,
        }
        schema = vol.Schema(
            {
                vol.Required(CONF_SHIFTS): _SHIFTS_SELECTOR,
                vol.Optional(CONF_SYNC_CALENDAR): _CALENDAR_SELECTOR,
            }
        )
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(schema, current),
            errors=errors,
            description_placeholders={"error": detail},
        )
