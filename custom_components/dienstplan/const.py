"""Konstanten für die Dienstplan-Integration."""

DOMAIN = "dienstplan"
VERSION = "0.5.0"

CONF_NAME = "name"
CONF_SHIFTS = "shifts"
CONF_SYNC_CALENDAR = "sync_calendar"
CONF_WEEKLY_HOURS = "weekly_hours"
CONF_VACATION_DAYS = "vacation_days"

STORAGE_VERSION = 2

CARD_URL = f"/{DOMAIN}_static/dienstplan-card.js"

PANEL_PATH = DOMAIN
PANEL_ELEMENT = "dienstplan-panel"
PANEL_ICON = "mdi:calendar-clock"

SERVICE_SET_SHIFT = "set_shift"
SERVICE_SET_SHIFTS = "set_shifts"
SERVICE_SYNC = "sync"
SERVICE_REGENERATE_LINK = "regenerate_link"
SERVICE_ASK = "ask"

WS_GET_DAYS = f"{DOMAIN}/get_days"
EVENT_LOOKAHEAD_DAYS = 90
SYNC_DAYS_BACK = 14
FEED_DAYS_BACK = 90
FEED_DAYS_AHEAD = 365
