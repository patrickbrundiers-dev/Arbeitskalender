"""Tests für das Eintragen der Karte als Dashboard-Ressource (ohne Home Assistant)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import re

from _loader import load

res = load("resources")
PATH = "/dienstplan_static/dienstplan-card.js"
ROOT = Path(__file__).resolve().parent.parent / "custom_components" / "dienstplan"


class FakeStorage:
    """Verhält sich wie ResourceStorageCollection (Laden nötig, Einträge als Dicts)."""

    def __init__(self, items=None, loaded=True):
        self.items = list(items or [])
        self.loaded = loaded
        self.load_calls = 0

    async def _async_ensure_loaded(self):
        if not self.loaded:
            self.load_calls += 1
            self.loaded = True

    def async_items(self):
        assert self.loaded, "Einträge vor dem Laden gelesen"
        return list(self.items)

    async def async_create_item(self, data):
        assert data["res_type"] == "module"
        self.items.append({"id": f"id{len(self.items) + 1}", "type": "module", "url": data["url"]})

    async def async_update_item(self, item_id, updates):
        next(i for i in self.items if i["id"] == item_id).update(updates)

    async def async_delete_item(self, item_id):
        self.items = [i for i in self.items if i["id"] != item_id]


class FakeYaml:
    """ResourceYAMLCollection: nur lesbar."""

    loaded = True

    def __init__(self, data):
        self.data = data

    def async_items(self):
        return self.data


def run(coro):
    return asyncio.run(coro)


def test_creates_when_missing_and_loads_first():
    col = FakeStorage(items=[{"id": "x", "type": "module", "url": "/local/other.js"}], loaded=False)
    assert run(res.async_ensure_resource(col, PATH, PATH + "?v=1")) == res.CREATED
    assert col.load_calls == 1
    assert [i["url"] for i in col.items] == ["/local/other.js", PATH + "?v=1"]


def test_idempotent_and_updates_version():
    col = FakeStorage()
    run(res.async_ensure_resource(col, PATH, PATH + "?v=1"))
    assert run(res.async_ensure_resource(col, PATH, PATH + "?v=1")) == res.UNCHANGED
    assert run(res.async_ensure_resource(col, PATH, PATH + "?v=2")) == res.UPDATED
    assert [i["url"] for i in col.items] == [PATH + "?v=2"], "kein zweiter Eintrag"


def test_leaves_foreign_resources_alone():
    other = {"id": "o", "type": "module", "url": "/hacsfiles/other-card/other-card.js"}
    col = FakeStorage(items=[other])
    run(res.async_ensure_resource(col, PATH, PATH + "?v=1"))
    run(res.async_remove_resource(col, PATH))
    assert col.items == [other]


def test_yaml_mode_and_unknown_are_unsupported():
    assert run(res.async_ensure_resource(FakeYaml([]), PATH, PATH)) == res.UNSUPPORTED
    assert run(res.async_ensure_resource(None, PATH, PATH)) == res.UNSUPPORTED
    assert run(res.async_remove_resource(FakeYaml([{"url": PATH}]), PATH)) == 0
    assert run(res.async_remove_resource(None, PATH)) == 0


def test_remove():
    col = FakeStorage()
    run(res.async_ensure_resource(col, PATH, PATH + "?v=1"))
    assert run(res.async_remove_resource(col, PATH)) == 1
    assert col.items == []
    assert run(res.async_remove_resource(col, PATH)) == 0


def test_version_is_consistent():
    """Die Kartenadresse trägt ?v=<Version>. Ohne Anheben der Version holen Browser die neue Karte nicht."""
    const = (ROOT / "const.py").read_text(encoding="utf-8")
    version = re.search(r'^VERSION = "([^"]+)"', const, re.M).group(1)
    manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["version"] == version, (manifest["version"], version)


def test_card_version_matches_integration():
    """Die Karte vergleicht ihre eigene Version mit der der Integration; beide müssen übereinstimmen."""
    const = (ROOT / "const.py").read_text(encoding="utf-8")
    version = re.search(r'^VERSION = "([^"]+)"', const, re.M).group(1)
    card = (ROOT / "frontend" / "dienstplan-card.js").read_text(encoding="utf-8")
    assert re.search(r'const CARD_VERSION = "([^"]+)"', card).group(1) == version


def test_manifest_lists_every_home_assistant_dependency_used():
    """Wer panel_custom/lovelace/frontend nutzt, muss es als Abhängigkeit nennen (sonst fehlt es beim Start)."""
    manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    source = (ROOT / "__init__.py").read_text(encoding="utf-8")
    for component in ("panel_custom", "frontend", "http", "websocket_api"):
        if re.search(rf"homeassistant\.components(\.{component}\b| import [^\n]*\b{component}\b)", source):
            assert component in manifest["dependencies"], component
    assert "lovelace" in manifest["dependencies"], "Dashboard-Ressourcen"
