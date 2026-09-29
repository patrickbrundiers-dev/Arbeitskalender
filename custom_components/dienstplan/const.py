"""Konstanten für die Dienstplan-Integration."""

DOMAIN = "dienstplan"
VERSION = "0.3.0"

CONF_NAME = "name"
CONF_SHIFTS = "shifts"
CONF_SYNC_CALENDAR = "sync_calendar"
CONF_WEEKLY_HOURS = "weekly_hours"
CONF_VACATION_DAYS = "vacation_days"

STORAGE_VERSION = 1

CARD_URL = f"/{DOMAIN}_static/dienstplan-card.js"

SERVICE_SET_SHIFT = "set_shift"
SERVICE_SET_SHIFTS = "set_shifts"
SERVICE_SYNC = "sync"
SERVICE_REGENERATE_LINK = "regenerate_link"

WS_GET_DAYS = f"{DOMAIN}/get_days"

# Wie viele Tage der Kalender-Entität als „nächster Termin“ vorausschaut
EVENT_LOOKAHEAD_DAYS = 90

# Ein vollständiger Abgleich betrachtet nur Tage ab „heute minus X“
SYNC_DAYS_BACK = 14

# Zeitfenster des iCal-Feeds
FEED_DAYS_BACK = 90
FEED_DAYS_AHEAD = 365
