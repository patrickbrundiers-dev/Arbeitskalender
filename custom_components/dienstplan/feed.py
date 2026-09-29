"""Öffentlicher iCal-Feed pro Person (Link mit geheimem Token)."""

from __future__ import annotations

import hmac

from aiohttp import web

from homeassistant.components.http import HomeAssistantView
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant

from .const import DOMAIN


class DienstplanFeedView(HomeAssistantView):
    """Liefert den Dienstplan als .ics zum Abonnieren (Google, Apple, Outlook …).

    Kalender-Apps können sich nicht bei Home Assistant anmelden, daher schützt
    ein zufälliger Token in der URL den Zugriff (``requires_auth = False``).
    """

    url = f"/api/{DOMAIN}/feed/{{entry_id}}/{{token}}/calendar.ics"
    name = f"api:{DOMAIN}:feed"
    requires_auth = False

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass

    async def get(self, request: web.Request, entry_id: str, token: str) -> web.Response:
        entry = next((e for e in self.hass.config_entries.async_entries(DOMAIN) if e.entry_id == entry_id), None)
        manager = getattr(entry, "runtime_data", None) if entry and entry.state is ConfigEntryState.LOADED else None
        if manager is None or not manager.token or not hmac.compare_digest(token.encode(), manager.token.encode()):
            return web.Response(status=404)
        return web.Response(
            text=manager.build_feed(),
            content_type="text/calendar",
            charset="utf-8",
            headers={"Cache-Control": "no-store"},
        )
