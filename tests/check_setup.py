"""Prüft das echte __init__.py (Einrichtung der Karte) mit minimalen Home-Assistant-Stubs.

Aufruf: ``python tests/check_setup.py``. Getestet wird: Karte wird mit Cache-Header und
Versions-Adresse ausgeliefert, als Dashboard-Ressource eingetragen (einmalig, mit
Versionswechsel), Fehler dabei stören die Einrichtung nie, und beim Entfernen der letzten
Einrichtung wird aufgeräumt. Ein Test in einer echten HA-Instanz ersetzt das nicht.
"""

import asyncio
import enum
import importlib.util
import logging
import sys
import types
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent / "custom_components" / "dienstplan"


def mod(name, **attrs):
    m = types.ModuleType(name)
    m.__dict__.update(attrs)
    sys.modules[name] = m
    return m


# ---------------------------------------------------------------- Stubs
try:
    import voluptuous  # noqa: F401
except ImportError:
    mod("voluptuous", Required=lambda key, **kw: key, Invalid=type("Invalid", (Exception,), {}))

calls = SimpleNamespace(js_urls=[], commands=[], views=[], static=[])


@dataclass
class StaticPathConfig:
    url_path: str
    path: str
    cache_headers: bool = True


class ConfigEntryState(enum.Enum):
    LOADED = "loaded"


class ConfigEntry:
    def __class_getitem__(cls, item):
        return cls


class Platform(str, enum.Enum):
    CALENDAR = "calendar"
    SENSOR = "sensor"


ws = mod(
    "homeassistant.components.websocket_api",
    websocket_command=lambda schema: (lambda fn: fn),
    async_register_command=lambda hass, fn: calls.commands.append(fn),
    ActiveConnection=object,
    ERR_NOT_FOUND="not_found",
)
frontend = mod("homeassistant.components.frontend", add_extra_js_url=lambda hass, url: calls.js_urls.append(url))
http = mod("homeassistant.components.http", StaticPathConfig=StaticPathConfig)
components = mod("homeassistant.components", websocket_api=ws, frontend=frontend, http=http)
cv = mod(
    "homeassistant.helpers.config_validation",
    config_entry_only_config_schema=lambda domain: {},
    entity_id=str,
    date=str,
)
er = mod("homeassistant.helpers.entity_registry", async_get=lambda hass: None)


class Store:
    removed = []

    def __init__(self, hass, version, key):
        self.key = key

    async def async_remove(self):
        Store.removed.append(self.key)


helpers = mod("homeassistant.helpers", config_validation=cv, entity_registry=er)
mod("homeassistant.helpers.storage", Store=Store)
mod("homeassistant.helpers.typing", ConfigType=dict)
mod("homeassistant.config_entries", ConfigEntry=ConfigEntry, ConfigEntryState=ConfigEntryState)
mod("homeassistant.const", Platform=Platform)
mod("homeassistant.core", HomeAssistant=object, callback=lambda fn: fn)
mod("homeassistant", components=components, helpers=helpers)

PKG = "dienstplan_setup"
spec = importlib.util.spec_from_file_location(PKG, ROOT / "__init__.py", submodule_search_locations=[str(ROOT)])
integration = importlib.util.module_from_spec(spec)
sys.modules[PKG] = integration
mod(f"{PKG}.feed", DienstplanFeedView=lambda hass: ("view", hass))
mod(f"{PKG}.manager", DienstplanManager=object)
spec.loader.exec_module(integration)

from importlib import import_module  # noqa: E402

const = import_module(f"{PKG}.const")


# ---------------------------------------------------------------- Fakes
class FakeResources:
    loaded = True

    def __init__(self, items=None, fail=False):
        self.items = list(items or [])
        self.fail = fail

    def async_items(self):
        return list(self.items)

    async def async_create_item(self, data):
        if self.fail:
            raise RuntimeError("Speicher kaputt")
        self.items.append({"id": f"id{len(self.items) + 1}", "type": "module", "url": data["url"]})

    async def async_update_item(self, item_id, updates):
        next(i for i in self.items if i["id"] == item_id).update(updates)

    async def async_delete_item(self, item_id):
        self.items = [i for i in self.items if i["id"] != item_id]


def make_hass(resources="default", entries=()):
    async def register_static(paths):
        calls.static.extend(paths)

    data = {}
    if resources == "default":
        data["lovelace"] = SimpleNamespace(resources=FakeResources())
    elif resources is not None:
        data["lovelace"] = SimpleNamespace(resources=resources)
    return SimpleNamespace(
        data=data,
        http=SimpleNamespace(async_register_static_paths=register_static, register_view=lambda v: calls.views.append(v)),
        config_entries=SimpleNamespace(async_entries=lambda domain: list(entries)),
    )


def reset():
    calls.js_urls.clear()
    calls.commands.clear()
    calls.views.clear()
    calls.static.clear()
    Store.removed.clear()


class LogCapture(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.records = []

    def emit(self, record):
        self.records.append(record)


log = LogCapture()
logging.getLogger(PKG).addHandler(log)
logging.getLogger(PKG).setLevel(logging.DEBUG)
run = asyncio.run
URL = f"{const.CARD_URL}?v={const.VERSION}"

# 1) Erststart: ausgeliefert mit Cache-Header, Versions-Adresse, Ressource angelegt
hass = make_hass()
assert run(integration.async_setup(hass, {})) is True
assert len(calls.static) == 1 and calls.static[0].url_path == const.CARD_URL and calls.static[0].cache_headers is True
assert calls.static[0].path.endswith("frontend/dienstplan-card.js") and Path(calls.static[0].path).is_file()
assert calls.js_urls == [URL], calls.js_urls
assert [i["url"] for i in hass.data["lovelace"].resources.items] == [URL]
assert calls.views and calls.commands

# 2) Neustart mit gleicher Version: kein zweiter Eintrag; Versionswechsel: Adresse wird angepasst
run(integration.async_setup(hass, {}))
assert len(hass.data["lovelace"].resources.items) == 1
hass.data["lovelace"].resources.items[0]["url"] = const.CARD_URL + "?v=0.0.1"
run(integration.async_setup(hass, {}))
assert [i["url"] for i in hass.data["lovelace"].resources.items] == [URL]

# 3) Fremde Ressourcen bleiben unberührt
other = {"id": "o", "type": "module", "url": "/hacsfiles/x/x.js"}
hass = make_hass(FakeResources([other]))
run(integration.async_setup(hass, {}))
assert other in hass.data["lovelace"].resources.items and len(hass.data["lovelace"].resources.items) == 2

# 4) Kein Lovelace / YAML-Modus / kaputter Speicher: Einrichtung gelingt trotzdem
for label, h in (
    ("ohne lovelace", make_hass(None)),
    ("yaml", make_hass(SimpleNamespace(async_items=lambda: []))),
    ("defekt", make_hass(FakeResources(fail=True))),
):
    reset()
    log.records.clear()
    assert run(integration.async_setup(h, {})) is True, label
    assert calls.js_urls == [URL], label  # Auslieferung wie gehabt
assert any(r.levelno == logging.WARNING for r in log.records), "Fehler wird protokolliert"

# 5) Entfernen: nur bei der letzten Einrichtung wird die Ressource ausgetragen
entry = SimpleNamespace(entry_id="e1")
hass = make_hass(entries=[entry, SimpleNamespace(entry_id="e2")])
run(integration.async_setup(hass, {}))
run(integration.async_remove_entry(hass, entry))
assert len(hass.data["lovelace"].resources.items) == 1, "noch eine Einrichtung übrig"
assert Store.removed == [f"{const.DOMAIN}.e1"]

hass = make_hass(entries=[entry])
run(integration.async_setup(hass, {}))
run(integration.async_remove_entry(hass, entry))
assert hass.data["lovelace"].resources.items == [], "letzte Einrichtung räumt auf"

print("Einrichtung: alle Prüfungen bestanden")
