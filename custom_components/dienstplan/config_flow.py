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
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
)

from .const import (
    CONF_NAME,
    CONF_SHIFTS,
    CONF_SYNC_CALENDAR,
    CONF_VACATION_DAYS,
    CONF_WEEKLY_HOURS,
    DOMAIN,
)
from .shifts import DEFAULT_SHIFTS_TEXT, ShiftParseError, parse_shifts

_LOGGER = logging.getLogger(__name__)

_SHIFTS_SELECTOR = TextSelector(TextSelectorConfig(multiline=True))
_CALENDAR_SELECTOR = EntitySelector(EntitySelectorConfig(domain="calendar"))
_HOURS_SELECTOR = NumberSelector(
    NumberSelectorConfig(min=0, max=60, step=0.25, mode=NumberSelectorMode.BOX, unit_of_measurement="h")
)
_DAYS_SELECTOR = NumberSelector(NumberSelectorConfig(min=0, max=60, step=1, mode=NumberSelectorMode.BOX))


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


def _normalized(user_input: dict[str, Any]) -> dict[str, Any]:
    """Optionale Felder immer speichern, damit gelöschte Werte nicht auf ältere zurückfallen."""
    return {
        CONF_SHIFTS: user_input[CONF_SHIFTS],
        CONF_SYNC_CALENDAR: user_input.get(CONF_SYNC_CALENDAR) or "",
        CONF_WEEKLY_HOURS: float(user_input.get(CONF_WEEKLY_HOURS) or 0),
        CONF_VACATION_DAYS: int(float(user_input.get(CONF_VACATION_DAYS) or 0)),
    }


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
                    data=_normalized(user_input),
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_NAME): str,
                vol.Required(CONF_SHIFTS): _SHIFTS_SELECTOR,
                vol.Optional(CONF_WEEKLY_HOURS): _HOURS_SELECTOR,
                vol.Optional(CONF_VACATION_DAYS): _DAYS_SELECTOR,
                vol.Optional(CONF_SYNC_CALENDAR): _CALENDAR_SELECTOR,
            }
        )
        suggested = user_input or {
            CONF_NAME: "Dienstplan",
            CONF_SHIFTS: DEFAULT_SHIFTS_TEXT,
            CONF_WEEKLY_HOURS: 0,
            CONF_VACATION_DAYS: 0,
        }
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(schema, suggested),
            errors=errors,
            description_placeholders={"error": detail},
        )


class DienstplanOptionsFlow(OptionsFlow):
    """Dienste, Soll-Stunden, Urlaub und Ziel-Kalender nachträglich ändern."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        detail = ""
        if user_input is not None:
            errors, detail = _validate(self.hass, user_input)
            if not errors:
                return self.async_create_entry(data=_normalized(user_input))

        entry = self.config_entry

        def stored(key: str, default: Any = None) -> Any:
            return entry.options.get(key, entry.data.get(key, default))

        current = user_input or {
            CONF_SHIFTS: stored(CONF_SHIFTS, DEFAULT_SHIFTS_TEXT),
            CONF_WEEKLY_HOURS: stored(CONF_WEEKLY_HOURS, 0),
            CONF_VACATION_DAYS: stored(CONF_VACATION_DAYS, 0),
            CONF_SYNC_CALENDAR: stored(CONF_SYNC_CALENDAR) or None,
        }
        schema = vol.Schema(
            {
                vol.Required(CONF_SHIFTS): _SHIFTS_SELECTOR,
                vol.Optional(CONF_WEEKLY_HOURS): _HOURS_SELECTOR,
                vol.Optional(CONF_VACATION_DAYS): _DAYS_SELECTOR,
                vol.Optional(CONF_SYNC_CALENDAR): _CALENDAR_SELECTOR,
            }
        )
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(schema, current),
            errors=errors,
            description_placeholders={"error": detail},
        )
