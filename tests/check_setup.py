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
from datetime import date, datetime
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
    mod(
        "voluptuous",
        Required=lambda key, **kw: key,
        Optional=lambda key, **kw: key,
        Schema=lambda schema, **kw: schema,
        Invalid=type("Invalid", (Exception,), {}),
    )

calls = SimpleNamespace(js_urls=[], commands=[], views=[], static=[])


@dataclass
class StaticPathConfig:
    url_path: str
    path: str
    cache_headers: bool = True


class ConfigEntryState(enum.Enum):
    LOADED = "loaded"
    NOT_LOADED = "not_loaded"


class SupportsResponse(enum.Enum):
    ONLY = "only"


NOW = datetime(2026, 9, 29, 10, 0)


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
    string=str,
)
REGISTRY = {}  # entry_id -> entity_id
er = mod(
    "homeassistant.helpers.entity_registry",
    async_get=lambda hass: SimpleNamespace(async_get_entity_id=lambda domain, platform, uid: REGISTRY.get(uid)),
)
dt_mod = mod("homeassistant.util.dt", now=lambda: NOW)
util = mod("homeassistant.util", dt=dt_mod)


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
mod("homeassistant.core", HomeAssistant=object, ServiceCall=object, SupportsResponse=SupportsResponse, callback=lambda fn: fn)
mod("homeassistant", components=components, helpers=helpers, util=util)

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


SERVICES = {}


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
        services=SimpleNamespace(async_register=lambda domain, name, fn, schema=None, supports_response=None: SERVICES.update({(domain, name): (fn, schema, supports_response)})),
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

# 6) Service dienstplan.ask: registriert, liefert Antwort, findet Einträge und Kalender
from importlib import import_module as _im  # noqa: E402

shifts = _im(f"{PKG}.shifts")
SHIFT_DEFS = shifts.parse_shifts("F1;Frühdienst 1;06:00;14:00;;;8\nU;Urlaub;;;urlaub")


def fake_entry(entry_id, title, plan, state=ConfigEntryState.LOADED):
    manager = SimpleNamespace(shift_on=lambda d: shifts.find_shift(SHIFT_DEFS, plan.get(d.isoformat())))
    return SimpleNamespace(entry_id=entry_id, title=title, state=state, runtime_data=manager)


jenny = fake_entry("e1", "Dienstplan Jenny", {"2026-09-30": "F1"})
max_ = fake_entry("e2", "Dienstplan Max", {"2026-09-30": "U"})
REGISTRY.update({"e1": "calendar.dienstplan_jenny_dienstplan", "e2": "calendar.dienstplan_max_dienstplan"})

SERVICES.clear()
hass = make_hass(entries=[jenny, max_])
run(integration.async_setup(hass, {}))
handler, schema, supports = SERVICES[(const.DOMAIN, "ask")]
assert supports is SupportsResponse.ONLY, "Service liefert nur eine Antwort"


def call(**data):
    return run(handler(SimpleNamespace(hass=hass, data=data)))


r = call(person="Jenny", day="morgen")
assert r["speech"] == "Jenny hat morgen Frühdienst 1, von 6 Uhr bis 14 Uhr.", r
assert r["people"][0]["entity_id"] == "calendar.dienstplan_jenny_dienstplan" and r["date"] == "2026-09-30"
r = call(person="", day="morgen")
assert r["speech"] == "Jenny hat morgen Frühdienst 1, von 6 Uhr bis 14 Uhr. Max hat morgen Urlaub.", r
r = call(entity_id="calendar.dienstplan_max_dienstplan", day="morgen")
assert r["speech"] == "Max hat morgen Urlaub.", r
assert call(entity_id="calendar.gibt_es_nicht")["speech"] == "Ich finde keinen geladenen Dienstplan."
assert call(person="Peter")["speech"] == "Für Peter habe ich keinen Dienstplan."

# nicht geladene Einträge werden übersprungen
max_.state = ConfigEntryState.NOT_LOADED
assert call(day="morgen")["speech"].startswith("Jenny hat morgen") and "Max" not in call(day="morgen")["speech"]

print("Einrichtung: alle Prüfungen bestanden")
