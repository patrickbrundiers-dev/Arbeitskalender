"""Karte als Dashboard-Ressource eintragen (best effort, ohne Home-Assistant-Importe).

Die Karte wird zusätzlich zu ``add_extra_js_url`` als Ressource des Dashboards
eingetragen. Ressourcen lädt das Dashboard bei jedem Öffnen selbst; die Karte
hängt dadurch nicht davon ab, ob die Seite vor dem Start der Integration geladen
wurde. Funktioniert nur, wenn die Ressourcen im Speichermodus laufen (Standard).
Im YAML-Modus oder bei unbekannter Home-Assistant-Version passiert nichts.
"""

from __future__ import annotations

from typing import Any

UNSUPPORTED = "unsupported"
CREATED = "created"
UPDATED = "updated"
UNCHANGED = "unchanged"


def _base(url: Any) -> str:
    """URL ohne Query-Teil (``?v=…``)."""
    return str(url or "").split("?", 1)[0]


def _can(resources: Any, *names: str) -> bool:
    return resources is not None and all(callable(getattr(resources, name, None)) for name in names)


async def _ensure_loaded(resources: Any) -> None:
    ensure = getattr(resources, "_async_ensure_loaded", None)
    if callable(ensure):
        await ensure()
    elif not getattr(resources, "loaded", True):
        await resources.async_load()


def _ours(resources: Any, path: str) -> list[dict]:
    return [item for item in resources.async_items() if _base(item.get("url")) == path]


async def async_ensure_resource(resources: Any, path: str, url: str) -> str:
    """Ressource anlegen oder auf die aktuelle URL (mit Version) bringen."""
    if not _can(resources, "async_items", "async_create_item", "async_update_item"):
        return UNSUPPORTED
    await _ensure_loaded(resources)
    ours = _ours(resources, path)
    if not ours:
        await resources.async_create_item({"res_type": "module", "url": url})
        return CREATED
    if ours[0].get("url") == url:
        return UNCHANGED
    await resources.async_update_item(ours[0]["id"], {"url": url})
    return UPDATED


async def async_remove_resource(resources: Any, path: str) -> int:
    """Unsere Ressource(n) entfernen. Gibt die Anzahl entfernter Einträge zurück."""
    if not _can(resources, "async_items", "async_delete_item"):
        return 0
    await _ensure_loaded(resources)
    removed = 0
    for item in _ours(resources, path):
        await resources.async_delete_item(item["id"])
        removed += 1
    return removed
