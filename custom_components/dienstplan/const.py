"""Konstanten für die Dienstplan-Integration."""

DOMAIN = "dienstplan"
VERSION = "0.1.0"

CONF_NAME = "name"
CONF_SHIFTS = "shifts"
CONF_SYNC_CALENDAR = "sync_calendar"

STORAGE_VERSION = 1

CARD_URL = f"/{DOMAIN}_static/dienstplan-card.js"

SERVICE_SET_SHIFT = "set_shift"
SERVICE_SET_SHIFTS = "set_shifts"
SERVICE_SYNC = "sync"

WS_GET_DAYS = f"{DOMAIN}/get_days"

# Wie viele Tage der Kalender-Entität als „nächster Termin“ vorausschaut
EVENT_LOOKAHEAD_DAYS = 90
