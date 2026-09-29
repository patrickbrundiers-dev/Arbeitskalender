"""Prüft das echte __init__.py (Einrichtung der Karte) mit minimalen Home-Assistant-Stubs.

Aufruf: ``python tests/check_setup.py``. Getestet wird: Die Karte wird über drei voneinander unabhängige
Wege bereitgestellt (Startseite, Dashboard-Ressource, Seitenleiste) unter einer Adresse mit Fingerabdruck
der Datei; scheitert ein Schritt, laufen die übrigen trotzdem; beim Entfernen der letzten Einrichtung wird
aufgeräumt. Die Signaturen der echten Home-Assistant-Funktionen sind separat gegen deren Quelltext
geprüft; ein Test in einer echten HA-Instanz ersetzt das trotzdem nicht.
"""

import asyncio
import enum
import hashlib
import importlib.util
import logging
import sys
import types
from dataclasses import dataclass
from pathlib import Path
from datetime import datetime
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

calls = SimpleNamespace(js_urls=[], commands=[], views=[], static=[], panels=[], removed_panels=[])
FAIL = set()  # Namen von Schritten, die im Test absichtlich scheitern
PANELS = set()  # bereits registrierte Seitenleisten-Seiten


def maybe_fail(name):
    if name in FAIL:
        raise RuntimeError(f"absichtlicher Fehler: {name}")


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
    async_register_command=lambda hass, fn: (maybe_fail("Websocket-Befehl"), calls.commands.append(fn)),
    ActiveConnection=object,
    ERR_NOT_FOUND="not_found",
)


def add_extra_js_url(hass, url):
    maybe_fail("Karte im Frontend anmelden")
    calls.js_urls.append(url)


def async_panel_exists(hass, path):
    return path in PANELS


def async_remove_panel(hass, path, *, warn_if_unknown=True):
    calls.removed_panels.append((path, warn_if_unknown))
    PANELS.discard(path)


frontend = mod(
    "homeassistant.components.frontend",
    add_extra_js_url=add_extra_js_url,
    async_panel_exists=async_panel_exists,
    async_remove_panel=async_remove_panel,
)
http = mod("homeassistant.components.http", StaticPathConfig=StaticPathConfig)


async def async_register_panel(hass, **kwargs):
    maybe_fail("Seitenleiste")
    calls.panels.append(kwargs)
    PANELS.add(kwargs["frontend_url_path"])


panel_custom = mod("homeassistant.components.panel_custom", async_register_panel=async_register_panel)
components = mod(
    "homeassistant.components", websocket_api=ws, frontend=frontend, http=http, panel_custom=panel_custom
)
cv = mod(
    "homeassistant.helpers.config_validation",
    config_entry_only_config_schema=lambda domain: {},
    entity_id=str,
    date=str,
    string=str,
)
REGISTRY = {}  # entry_id -> entity_id
ENTITY_ENTRIES = {}  # entity_id -> Registry-Eintrag
er = mod(
    "homeassistant.helpers.entity_registry",
    async_get=lambda hass: SimpleNamespace(
        async_get_entity_id=lambda domain, platform, uid: REGISTRY.get(uid),
        async_get=lambda entity_id: ENTITY_ENTRIES.get(entity_id),
    ),
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
        assert data["res_type"] == "module"
        self.items.append({"id": f"id{len(self.items) + 1}", "type": "module", "url": data["url"]})

    async def async_update_item(self, item_id, updates):
        next(i for i in self.items if i["id"] == item_id).update(updates)

    async def async_delete_item(self, item_id):
        self.items = [i for i in self.items if i["id"] != item_id]


SERVICES = {}


def make_hass(resources="default", entries=(), entry_by_id=None):
    async def register_static(paths):
        maybe_fail("Karte ausliefern")
        calls.static.extend(paths)

    async def executor(fn, *args):
        return fn(*args)

    def register_service(domain, name, fn, schema=None, supports_response=None):
        maybe_fail("Sprachdienst")
        SERVICES[(domain, name)] = (fn, schema, supports_response)

    data = {}
    if resources == "default":
        data["lovelace"] = SimpleNamespace(resources=FakeResources())
    elif resources is not None:
        data["lovelace"] = SimpleNamespace(resources=resources)
    return SimpleNamespace(
        data=data,
        async_add_executor_job=executor,
        services=SimpleNamespace(async_register=register_service),
        http=SimpleNamespace(async_register_static_paths=register_static, register_view=lambda v: (maybe_fail("iCal-Feed"), calls.views.append(v))),
        config_entries=SimpleNamespace(
            async_entries=lambda domain: list(entries),
            async_get_entry=lambda entry_id: (entry_by_id or {}).get(entry_id),
        ),
    )


def reset():
    calls.js_urls.clear()
    calls.commands.clear()
    calls.views.clear()
    calls.static.clear()
    calls.panels.clear()
    calls.removed_panels.clear()
    PANELS.clear()
    SERVICES.clear()
    FAIL.clear()
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

DIGEST = hashlib.sha256((ROOT / "frontend" / "dienstplan-card.js").read_bytes()).hexdigest()[:8]
URL = f"{const.CARD_URL}?v={const.VERSION}-{DIGEST}"


def all_ways_ran(label):
    """Jeder unabhängige Weg wurde ausgeführt."""
    assert len(calls.static) == 1, label
    assert calls.js_urls == [URL], (label, calls.js_urls)
    assert len(calls.panels) == 1, label
    assert calls.views and calls.commands, label
    assert (const.DOMAIN, "ask") in SERVICES, label


# 1) Erststart: alle drei Wege, Adresse mit Version und Fingerabdruck, Cache-Header
reset()
log.records.clear()
hass = make_hass()
assert run(integration.async_setup(hass, {})) is True
all_ways_ran("erststart")
assert calls.static[0].url_path == const.CARD_URL and calls.static[0].cache_headers is True
assert calls.static[0].path.endswith("frontend/dienstplan-card.js") and Path(calls.static[0].path).is_file()
assert [i["url"] for i in hass.data["lovelace"].resources.items] == [URL]
panel = calls.panels[0]
assert panel["frontend_url_path"] == const.PANEL_PATH == "dienstplan"
assert panel["webcomponent_name"] == const.PANEL_ELEMENT == "dienstplan-panel"
assert panel["module_url"] == URL and panel["sidebar_title"] == "Dienstplan" and panel["require_admin"] is False
assert panel["sidebar_icon"] == const.PANEL_ICON
summary = [r.getMessage() for r in log.records if r.levelno == logging.INFO and "gestartet" in r.getMessage()]
assert summary and const.VERSION in summary[0] and URL in summary[0], summary
assert "Dashboard-Ressource: created" in summary[0] and "Seitenleiste: ok" in summary[0], summary[0]
assert not [r for r in log.records if r.levelno >= logging.WARNING], "im Normalfall keine Warnung"

# Der Fingerabdruck ändert sich mit dem Inhalt (sonst würde ein Zwischenspeicher eine alte Karte ausliefern)
assert integration._card_digest(ROOT / "frontend" / "dienstplan-card.js") == DIGEST
tmp = Path(__file__).parent / "_digest_probe.js"
try:
    tmp.write_text("a", encoding="utf-8")
    first = integration._card_digest(tmp)
    tmp.write_text("b", encoding="utf-8")
    assert first != integration._card_digest(tmp)
finally:
    tmp.unlink(missing_ok=True)
assert integration._card_digest(Path("/gibt/es/nicht.js")) is None

# 2) Neustart mit gleicher Version: kein zweiter Eintrag, Seite nicht doppelt; Versionswechsel: Adresse wird angepasst
run(integration.async_setup(hass, {}))
assert len(hass.data["lovelace"].resources.items) == 1
assert len(calls.panels) == 1, "Seite nur einmal anlegen"
hass.data["lovelace"].resources.items[0]["url"] = const.CARD_URL + "?v=0.0.1"
run(integration.async_setup(hass, {}))
assert [i["url"] for i in hass.data["lovelace"].resources.items] == [URL]

# 3) Fremde Ressourcen bleiben unberührt
reset()
other = {"id": "o", "type": "module", "url": "/hacsfiles/x/x.js"}
hass = make_hass(FakeResources([other]))
run(integration.async_setup(hass, {}))
assert other in hass.data["lovelace"].resources.items and len(hass.data["lovelace"].resources.items) == 2

# 4) Kein Lovelace / YAML-Modus / kaputter Speicher: Einrichtung gelingt, die anderen Wege laufen
for label, h in (
    ("ohne lovelace", make_hass(None)),
    ("yaml", make_hass(SimpleNamespace(async_items=lambda: []))),
    ("defekt", make_hass(FakeResources(fail=True))),
):
    reset()
    log.records.clear()
    assert run(integration.async_setup(h, {})) is True, label
    all_ways_ran(label)
assert any(r.levelno == logging.WARNING for r in log.records), "Fehler der Ressource wird protokolliert"

# 5) Jeder Schritt ist für sich abgesichert: scheitert einer, laufen alle anderen und die Einrichtung gelingt
for failing in (
    "Karte ausliefern",
    "Karte im Frontend anmelden",
    "Seitenleiste",
    "iCal-Feed",
    "Websocket-Befehl",
    "Sprachdienst",
):
    reset()
    log.records.clear()
    FAIL.add(failing)
    hass = make_hass()
    assert run(integration.async_setup(hass, {})) is True, failing
    errors = [r for r in log.records if r.levelno == logging.ERROR and failing in r.getMessage()]
    assert errors and errors[0].exc_info, f"{failing}: Fehler mit Ablaufverfolgung protokolliert"
    assert [i["url"] for i in hass.data["lovelace"].resources.items] == [URL], f"{failing}: Ressource trotzdem"
    ran = {
        "Karte ausliefern": bool(calls.static),
        "Karte im Frontend anmelden": bool(calls.js_urls),
        "Seitenleiste": bool(calls.panels),
        "iCal-Feed": bool(calls.views),
        "Websocket-Befehl": bool(calls.commands),
        "Sprachdienst": (const.DOMAIN, "ask") in SERVICES,
    }
    for step, done in ran.items():
        assert done is (step != failing), f"{failing}: Schritt „{step}“ {'lief nicht' if step != failing else 'lief trotz Fehler'}"
    assert any("FEHLER" in r.getMessage() for r in log.records if "gestartet" in r.getMessage()), "Zusammenfassung nennt den Fehler"

# 6) Kartendatei fehlt (z. B. unvollständiger HACS-Download): deutliche Fehlermeldung, Einrichtung gelingt
reset()
log.records.clear()
real_file = integration.CARD_FILE
integration.CARD_FILE = ROOT / "frontend" / "gibt-es-nicht.js"
try:
    hass = make_hass()
    assert run(integration.async_setup(hass, {})) is True
finally:
    integration.CARD_FILE = real_file
assert any(r.levelno == logging.ERROR and "Kartendatei fehlt" in r.getMessage() for r in log.records)
assert calls.js_urls == [f"{const.CARD_URL}?v={const.VERSION}"], "ohne Datei keine Fingerabdruck-Adresse"

# 7) Entfernen: nur bei der letzten Einrichtung werden Ressource und Seite ausgetragen
reset()
entry = SimpleNamespace(entry_id="e1")
hass = make_hass(entries=[entry, SimpleNamespace(entry_id="e2")])
run(integration.async_setup(hass, {}))
run(integration.async_remove_entry(hass, entry))
assert len(hass.data["lovelace"].resources.items) == 1, "noch eine Einrichtung übrig"
assert calls.removed_panels == [] and "dienstplan" in PANELS
assert Store.removed == [f"{const.DOMAIN}.e1"]

hass = make_hass(entries=[entry])
run(integration.async_setup(hass, {}))
run(integration.async_remove_entry(hass, entry))
assert hass.data["lovelace"].resources.items == [], "letzte Einrichtung räumt auf"
assert calls.removed_panels == [("dienstplan", True)], "Seite wird entfernt (nur wenn es sie gibt)"

# Ältere Home-Assistant-Versionen haben async_panel_exists noch nicht: kein Importfehler, Prüfung über die Panel-Liste
reset()
saved = frontend.async_panel_exists
del frontend.async_panel_exists
try:
    hass = make_hass()
    hass.data["frontend_panels"] = {"dienstplan": object()}
    assert run(integration.async_setup(hass, {})) is True
    assert calls.panels == [], "vorhandene Seite wird nicht doppelt angelegt"
    hass = make_hass()
    assert run(integration.async_setup(hass, {})) is True
    assert len(calls.panels) == 1
finally:
    frontend.async_panel_exists = saved

# Aufräumen darf nie scheitern
reset()
hass = make_hass(FakeResources(fail=True), entries=[entry])
run(integration.async_setup(hass, {}))
run(integration.async_remove_entry(hass, entry))

# 8) Service dienstplan.ask: registriert, liefert Antwort, findet Einträge und Kalender
from importlib import import_module as _im  # noqa: E402

shifts = _im(f"{PKG}.shifts")
SHIFT_DEFS = shifts.parse_shifts("F1;Frühdienst 1;06:00;14:00;;;8\nU;Urlaub;;;urlaub")


def fake_entry(entry_id, title, plan, state=ConfigEntryState.LOADED):
    manager = SimpleNamespace(shift_on=lambda d: shifts.find_shift(SHIFT_DEFS, plan.get(d.isoformat())))
    return SimpleNamespace(entry_id=entry_id, title=title, state=state, runtime_data=manager)


jenny = fake_entry("e1", "Dienstplan Jenny", {"2026-09-30": "F1"})
max_ = fake_entry("e2", "Dienstplan Max", {"2026-09-30": "U"})
REGISTRY.update({"e1": "calendar.dienstplan_jenny_dienstplan", "e2": "calendar.dienstplan_max_dienstplan"})

reset()
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

# 9) Websocket-Befehl: meldet die Version der Integration (die Karte erkennt damit einen veralteten Zwischenspeicher)
manager = SimpleNamespace(
    shifts={"F1": SimpleNamespace(as_dict=lambda: {"code": "F1"})},
    days_between=lambda start, end: {"2026-09-30": "F1"},
    stats_range=lambda start, end: {},
    sync_calendar=None,
    feed_url=lambda: "https://ha.example/feed.ics",
)
loaded = SimpleNamespace(state=ConfigEntryState.LOADED, runtime_data=manager)
ENTITY_ENTRIES["calendar.jenny"] = SimpleNamespace(platform="dienstplan", config_entry_id="e1")
ENTITY_ENTRIES["calendar.fremd"] = SimpleNamespace(platform="google", config_entry_id="g1")
hass = make_hass(entry_by_id={"e1": loaded})
results, errors = [], []
connection = SimpleNamespace(
    send_result=lambda msg_id, result: results.append((msg_id, result)),
    send_error=lambda msg_id, code, text: errors.append((msg_id, code)),
)
integration.ws_get_days(hass, connection, {"id": 7, "entity_id": "calendar.jenny", "start": "a", "end": "b"})
assert results and results[0][0] == 7 and results[0][1]["version"] == const.VERSION, results
assert results[0][1]["days"] == {"2026-09-30": "F1"} and results[0][1]["shifts"] == [{"code": "F1"}]
integration.ws_get_days(hass, connection, {"id": 8, "entity_id": "calendar.fremd", "start": "a", "end": "b"})
integration.ws_get_days(hass, connection, {"id": 9, "entity_id": "calendar.unbekannt", "start": "a", "end": "b"})
assert errors == [(8, "not_found"), (9, "not_found")], errors

print("Einrichtung: alle Prüfungen bestanden")
