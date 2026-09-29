"""Konstanten für die Dienstplan-Integration."""

DOMAIN = "dienstplan"
VERSION = "0.4.1"

CONF_NAME = "name"
CONF_SHIFTS = "shifts"
CONF_SYNC_CALENDAR = "sync_calendar"
CONF_WEEKLY_HOURS = "weekly_hours"
CONF_VACATION_DAYS = "vacation_days"

STORAGE_VERSION = 1

CARD_URL = f"/{DOMAIN}_static/dienstplan-card.js"

# Eigene Seite in der Seitenleiste: lädt die Karte selbst und hängt nicht von der Startseite
# (index.html) oder vom Dashboard ab. Damit gibt es immer einen Weg, der funktioniert.
PANEL_PATH = DOMAIN
PANEL_ELEMENT = "dienstplan-panel"
PANEL_ICON = "mdi:calendar-clock"

SERVICE_SET_SHIFT = "set_shift"
SERVICE_SET_SHIFTS = "set_shifts"
SERVICE_SYNC = "sync"
SERVICE_REGENERATE_LINK = "regenerate_link"
SERVICE_ASK = "ask"

WS_GET_DAYS = f"{DOMAIN}/get_days"

# Wie viele Tage der Kalender-Entität als „nächster Termin“ vorausschaut
EVENT_LOOKAHEAD_DAYS = 90

# Ein vollständiger Abgleich betrachtet nur Tage ab „heute minus X“
SYNC_DAYS_BACK = 14

# Zeitfenster des iCal-Feeds
FEED_DAYS_BACK = 90
FEED_DAYS_AHEAD = 365
