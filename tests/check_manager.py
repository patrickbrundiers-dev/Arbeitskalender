"""Prüft manager.py mit minimalen Home-Assistant-Stubs.

Home Assistant selbst ist dafür nicht nötig: ``python tests/check_manager.py``.
Getestet werden Termine, Abgleich (Signaturen, Zielwechsel, Zeitfenster), Feed-Token,
Statistik und Sensor-Grundlagen. Ein Test in einer echten HA-Instanz ersetzt das nicht.
"""

import asyncio
import enum
import sys
import types
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Berlin")


def mod(name, **attrs):
    m = types.ModuleType(name)
    m.__dict__.update(attrs)
    sys.modules[name] = m
    return m


try:
    import voluptuous  # noqa: F401
except ImportError:
    mod("voluptuous", Invalid=type("Invalid", (Exception,), {}))


class HomeAssistantError(Exception):
    pass


class ServiceValidationError(HomeAssistantError):
    def __init__(self, *a, translation_domain=None, translation_key=None, translation_placeholders=None):
        super().__init__(translation_key)
        self.translation_key = translation_key


class NoURLAvailableError(Exception):
    pass


@dataclass
class CalendarEvent:
    start: object
    end: object
    summary: str
    description: str | None = None
    location: str | None = None
    uid: str | None = None


class CalendarEntityFeature(enum.IntFlag):
    CREATE_EVENT = 1
    DELETE_EVENT = 2
    UPDATE_EVENT = 4


NOTIFICATIONS = []
URL_MODE = {"available": True}


class Store:
    DB = {}

    def __init__(self, hass, version, key):
        self.key = key

    async def async_load(self):
        data = Store.DB.get(self.key)
        return None if data is None else {k: (dict(v) if isinstance(v, dict) else v) for k, v in data.items()}

    async def async_save(self, data):
        Store.DB[self.key] = {k: (dict(v) if isinstance(v, dict) else v) for k, v in data.items()}

    async def async_remove(self):
        Store.DB.pop(self.key, None)


def get_url(hass, prefer_external=False):
    if not URL_MODE["available"]:
        raise NoURLAvailableError
    return "https://ha.example"


mod("homeassistant")
mod("homeassistant.components")
mod(
    "homeassistant.components.persistent_notification",
    async_create=lambda hass, msg, title=None, notification_id=None: NOTIFICATIONS.append((title, msg)),
)
sys.modules["homeassistant.components"].persistent_notification = sys.modules[
    "homeassistant.components.persistent_notification"
]
mod("homeassistant.components.calendar", CalendarEntityFeature=CalendarEntityFeature, CalendarEvent=CalendarEvent)
mod("homeassistant.config_entries", ConfigEntry=object)
mod("homeassistant.core", HomeAssistant=object, callback=lambda f: f)
mod("homeassistant.exceptions", HomeAssistantError=HomeAssistantError, ServiceValidationError=ServiceValidationError)
mod("homeassistant.helpers")
mod("homeassistant.helpers.storage", Store=Store)
mod("homeassistant.helpers.network", get_url=get_url, NoURLAvailableError=NoURLAvailableError)
mod(
    "homeassistant.util.dt",
    get_default_time_zone=lambda: TZ,
    as_local=lambda d: d.astimezone(TZ),
    now=lambda: datetime.now(TZ),
    utcnow=lambda: datetime.now(ZoneInfo("UTC")),
)
mod("homeassistant.util")
sys.modules["homeassistant.util"].dt = sys.modules["homeassistant.util.dt"]

pkg = types.ModuleType("dienstplan")
pkg.__path__ = [str(Path(__file__).resolve().parent.parent / "custom_components" / "dienstplan")]
sys.modules["dienstplan"] = pkg
from dienstplan.const import (  # noqa: E402
    CONF_SHIFTS,
    CONF_SYNC_CALENDAR,
    CONF_VACATION_DAYS,
    CONF_WEEKLY_HOURS,
)
from dienstplan.manager import DienstplanManager  # noqa: E402


class RemoteCal:
    """Fake Ziel-Kalender."""

    def __init__(self, can_delete=True):
        self.events = []
        self.supported_features = CalendarEntityFeature.CREATE_EVENT | (
            CalendarEntityFeature.DELETE_EVENT if can_delete else 0
        )
        self.n = 0

    async def async_get_events(self, hass, start, end):
        return list(self.events)

    async def async_delete_event(self, uid):
        self.events = [e for e in self.events if e.uid != uid]


class Component:
    def __init__(self, entities):
        self.entities = entities

    def get_entity(self, eid):
        return self.entities.get(eid)


class Services:
    def __init__(self, remotes):
        self.remotes = remotes
        self.calls = []
        self.fail = False

    async def async_call(self, domain, service, data, blocking=False):
        assert (domain, service) == ("calendar", "create_event") and blocking
        if self.fail:
            raise HomeAssistantError("boom")
        self.calls.append(data)
        remote = self.remotes[data["entity_id"]]
        remote.n += 1
        remote.events.append(
            CalendarEvent(
                start=None,
                end=None,
                summary=data["summary"],
                description=data["description"],
                uid=f"uid{remote.n}",
            )
        )


class Hass:
    def __init__(self, remotes):
        self.data = {"calendar": Component(remotes)}
        self.services = Services(remotes)


SHIFTS = (
    "F1;Frühdienst 1;06:00;14:00\nS1;Spätdienst 1;13:00;21:00\nN1;Nachtdienst 1;21:00;06:00\n"
    "U;Urlaub;;;urlaub\nK;Krank;;;abwesend\nX;Frei;;;frei"
)


class Entry:
    def __init__(self, sync="calendar.ziel", shifts=SHIFTS, weekly=0, vacation=0):
        self.entry_id = "e1"
        self.title = "Jenny"
        self.options = {}
        self.data = {
            CONF_SHIFTS: shifts,
            CONF_SYNC_CALENDAR: sync,
            CONF_WEEKLY_HOURS: weekly,
            CONF_VACATION_DAYS: vacation,
        }


def run(coro):
    return asyncio.run(coro)


def make(can_delete=True, sync="calendar.ziel", **kw):
    Store.DB.clear()
    NOTIFICATIONS.clear()
    URL_MODE["available"] = True
    remotes = {"calendar.ziel": RemoteCal(can_delete), "calendar.ziel2": RemoteCal(can_delete)}
    hass = Hass(remotes)
    mgr = DienstplanManager(hass, Entry(sync=sync, **kw))
    run(mgr.async_load())
    return hass, remotes["calendar.ziel"], mgr


def reopen(hass, **kw):
    """Neuer Manager auf denselben gespeicherten Daten (wie nach Neustart/Reload)."""
    mgr = DienstplanManager(hass, Entry(**kw))
    run(mgr.async_load())
    return mgr


def D(s):
    return date.fromisoformat(s)


TODAY = datetime.now(TZ).date()


def day(offset):
    return TODAY + timedelta(days=offset)


# 1) Termine der eigenen Kalender-Entität
hass, remote, m = make(sync="")
run(m.async_set_days({D("2026-09-29"): "F1", D("2026-09-30"): "N1", D("2026-10-02"): "X", D("2026-10-03"): "u"}))
ev = m.events_between(datetime(2026, 9, 29, 0, 0, tzinfo=TZ), datetime(2026, 10, 5, 0, 0, tzinfo=TZ))
assert [e.summary for e in ev] == ["Frühdienst 1", "Nachtdienst 1", "Urlaub"], [e.summary for e in ev]
assert ev[1].end == datetime(2026, 10, 1, 6, 0, tzinfo=TZ)
assert m.days["2026-10-03"] == "U"
assert hass.services.calls == [], "ohne Ziel-Kalender kein Abgleich"
ev = m.events_between(datetime(2026, 10, 1, 0, 0, tzinfo=TZ), datetime(2026, 10, 1, 23, 0, tzinfo=TZ))
assert [e.summary for e in ev] == ["Nachtdienst 1"], "Nachtdienst vom Vortag ragt in den Tag"
assert m.events_between(datetime(2026, 10, 1, 7, 0, tzinfo=TZ), datetime(2026, 10, 2, 0, 0, tzinfo=TZ)) == []
m2 = reopen(hass, sync="")
assert m2.days == m.days, "Persistenz"
before = dict(m.days)
try:
    run(m.async_set_days({D("2026-11-01"): "F1", D("2026-11-02"): "Q9"}))
    raise AssertionError("hätte fehlschlagen müssen")
except ServiceValidationError as e:
    assert e.translation_key == "unknown_shift"
assert m.days == before, "alles oder nichts"
run(m.async_set_days({D("2026-10-03"): ""}))
assert "2026-10-03" not in m.days

# 2) Abgleich: Erstellen (zeitlich + ganztägig), X wird nicht übertragen
hass, remote, m = make()
run(m.async_set_days({D("2026-09-29"): "F1", D("2026-09-30"): "N1", D("2026-10-01"): "U", D("2026-10-02"): "X"}))
calls = hass.services.calls
assert len(calls) == 3, calls
assert calls[0]["entity_id"] == "calendar.ziel" and calls[0]["summary"] == "Frühdienst 1"
assert calls[0]["start_date_time"].startswith("2026-09-29T06:00:00+02:00")
assert calls[0]["end_date_time"].startswith("2026-09-29T14:00:00+02:00")
assert calls[1]["end_date_time"].startswith("2026-10-01T06:00:00+02:00")
assert calls[2]["start_date"] == "2026-10-01" and calls[2]["end_date"] == "2026-10-02"
assert "start_date_time" not in calls[2]
assert "[dienstplan:e1:2026-09-29]" in calls[0]["description"]
assert set(m.synced) == {"2026-09-29", "2026-09-30", "2026-10-01"}
assert m.synced["2026-09-29"].startswith("F1|Frühdienst 1|06:00|14:00")
run(m.async_set_days({D("2026-09-29"): "F1"}))
assert len(hass.services.calls) == 3
run(m.async_sync())  # Fenster: liegt in der Vergangenheit? 2026-09-29 ist evtl. älter als 14 Tage
n_after_full = len(hass.services.calls)
assert n_after_full == 3, "vollständiger Abgleich ohne Änderungen erzeugt nichts"

# 3) Änderung ersetzt den Termin (löschen + neu anlegen)
run(m.async_set_days({D("2026-09-29"): "S1"}))
assert [e.summary for e in remote.events if "2026-09-29" in e.description] == ["Spätdienst 1"]
assert len(remote.events) == 3 and m.synced["2026-09-29"].startswith("S1|") and not NOTIFICATIONS

# 4) Löschen / frei entfernt den Termin
run(m.async_set_days({D("2026-09-30"): ""}))
assert all("2026-09-30" not in e.description for e in remote.events) and "2026-09-30" not in m.synced
run(m.async_set_days({D("2026-10-01"): "X"}))
assert all("2026-10-01" not in e.description for e in remote.events) and "2026-10-01" not in m.synced

# 5) Ziel-Kalender ohne Löschen: neuer Termin wird angelegt, Hinweis erscheint
hass, remote, m = make(can_delete=False)
run(m.async_set_days({D("2026-09-29"): "F1"}))
assert not NOTIFICATIONS
run(m.async_set_days({D("2026-09-29"): "S1"}))
assert len(remote.events) == 2 and NOTIFICATIONS and "29.09.2026 (F1)" in NOTIFICATIONS[0][1], NOTIFICATIONS
assert m.synced["2026-09-29"].startswith("S1|")

# 6) Fehler beim Anlegen: nicht als übertragen markiert, sync wiederholt den Versuch
hass, remote, m = make()
hass.services.fail = True
run(m.async_set_days({D("2026-09-29"): "F1"}))
assert m.synced == {} and NOTIFICATIONS and "29.09.2026 (F1)" in NOTIFICATIONS[0][1]
hass.services.fail = False
NOTIFICATIONS.clear()
run(m.async_sync({"2026-09-29"}))
assert set(m.synced) == {"2026-09-29"} and len(remote.events) == 1 and not NOTIFICATIONS

# 7) Fremde Termine ohne Marker werden nie gelöscht
hass, remote, m = make()
remote.events.append(CalendarEvent(start=None, end=None, summary="Zahnarzt", description="anderer Termin", uid="fremd"))
run(m.async_set_days({D("2026-09-29"): "F1"}))
run(m.async_set_days({D("2026-09-29"): ""}))
assert [e.uid for e in remote.events] == ["fremd"]

# 8) Optionen: Ziel entfernt ("" überschreibt data)
e = Entry()
e.options = {CONF_SYNC_CALENDAR: ""}
assert DienstplanManager(hass, e).sync_calendar is None

# 9) Geänderte Dienstdefinition (Uhrzeit): vollständiger Abgleich ersetzt nur betroffene Tage
hass, remote, m = make()
run(m.async_set_days({day(1): "F1", day(2): "S1", day(3): "F1"}))
assert len(remote.events) == 3
hass.services.calls.clear()
m_new = reopen(
    hass,
    shifts=SHIFTS.replace("F1;Frühdienst 1;06:00;14:00", "F1;Frühdienst 1;06:30;13:00"),
)
run(m_new.async_sync())
assert len(hass.services.calls) == 2, [c["summary"] for c in hass.services.calls]  # beide F1-Tage, nicht S1
assert all(c["start_date_time"][11:16] == "06:30" for c in hass.services.calls)
assert len(remote.events) == 3, "alte F1-Termine wurden gelöscht, neue angelegt"
run(m_new.async_sync())
assert len(hass.services.calls) == 2, "danach stabil"

# 10) Wechsel des Ziel-Kalenders bereinigt den alten Kalender und überträgt alles neu
hass, remote, m = make()
run(m.async_set_days({day(1): "F1", day(2): "S1"}))
hass.services.calls.clear()
m_new = reopen(hass, sync="calendar.ziel2")
run(m_new.async_sync())
assert [c["entity_id"] for c in hass.services.calls] == ["calendar.ziel2", "calendar.ziel2"]
assert m_new.synced_target == "calendar.ziel2" and len(remote.events) == 2
assert all(e.description and "[dienstplan:e1:" not in e.description for e in remote.events) is False
assert all(c["entity_id"] == "calendar.ziel2" for c in hass.services.calls)
# Ziel entfernt: eigener alter Kalender wird bereinigt und der Zustand wird deaktiviert
m_none = reopen(hass, sync="")
run(m_none.async_sync())
assert m_none.synced_target is None
assert len(remote.events) == 0

# 11) Zeitfenster: ältere Tage nur bei ausdrücklicher Änderung
hass, remote, m = make()
old, recent = day(-40), day(-3)
m.days[old.isoformat()] = "F1"
m.days[recent.isoformat()] = "F1"
run(m.async_sync())
assert [c["start_date_time"][:10] for c in hass.services.calls] == [recent.isoformat()]
run(m.async_sync({old.isoformat()}))
assert len(hass.services.calls) == 2

# 12) Feed-Token und Feed
hass, remote, m = make()
token = m.token
assert len(token) >= 24 and reopen(hass).token == token, "Token bleibt stabil"
assert m.feed_path() == f"/api/dienstplan/feed/e1/{token}/calendar.ics"
assert m.feed_url() == f"https://ha.example{m.feed_path()}"
URL_MODE["available"] = False
assert m.feed_url() == m.feed_path(), "ohne URL nur der Pfad"
run(m.async_set_days({day(1): "F1", day(2): "U", day(3): "X", day(-200): "F1"}))
ics = m.build_feed()
assert ics.startswith("BEGIN:VCALENDAR\r\n") and ics.count("BEGIN:VEVENT") == 2, ics
assert "SUMMARY:Frühdienst 1" in ics and "SUMMARY:Urlaub" in ics and "Frei" not in ics
assert f"UID:e1-{day(1).isoformat()}@dienstplan" in ics
run(m.async_regenerate_token())
assert m.token != token and reopen(hass).token == m.token

# 13) Statistik über den Manager
hass, remote, m = make(sync="", weekly=38.5, vacation=30)
monday = D("2026-09-28")
run(m.async_set_days({D("2026-09-28"): "F1", D("2026-09-29"): "U", D("2026-09-30"): "U", D("2026-10-03"): "U"}))
assert m.week_stats(monday) == {"hours": 8 + 7.7 * 2, "target": 38.5, "balance": round(8 + 15.4 - 38.5, 2), "missing": 0}
assert m.vacation_taken(2026) == 2 and m.vacation_left(2026) == 28
assert list(m.stats_range(D("2026-08-31"), D("2026-10-04")))[-1] == "2026-09-28"
hass, remote, m = make(sync="")
assert m.weekly_hours == 0 and m.vacation_days == 0 and m.vacation_left(2026) is None

# 14) Nächster Dienstbeginn
hass, remote, m = make(sync="")
assert m.next_work_start() is None
run(m.async_set_days({day(3): "S1", day(1): "N1", day(2): "U", day(-1): "F1"}))
start, shift = m.next_work_start()
assert shift.code == "N1" and start.date() == day(1) and start.hour == 21
run(m.async_set_days({day(1): "X"}))
assert m.next_work_start()[1].code == "S1", "frei/Urlaub zählen nicht"


# 15) Storage-Aufräumen entfernt nur sehr alte Einträge
hass, remote, m = make(sync="")
m.days[(TODAY - timedelta(days=800)).isoformat()] = "F1"
m.days[(TODAY - timedelta(days=100)).isoformat()] = "F1"
run(m.async_prune_storage())
assert (TODAY - timedelta(days=800)).isoformat() not in m.days
assert (TODAY - timedelta(days=100)).isoformat() in m.days

print("Manager: alle Prüfungen bestanden")
