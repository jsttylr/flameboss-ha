"""Constants for the Flame Boss / EGG Genius integration."""

DOMAIN = "flameboss"

CONF_DEVICE_ID = "device_id"
CONF_PIN = "pin"

DEFAULT_PORT = 1883
# Flame Boss's documented username for the controller's local broker.
DEFAULT_USERNAME = "fb"

# The controller reports "no probe plugged in" with this value.
NO_PROBE = -32767

# Fallback setpoint limits in Celsius if the controller never sends its own.
DEFAULT_MIN_TEMP_C = 38.0
DEFAULT_MAX_TEMP_C = 343.0

# Number of probe slots in the "temps" array: index 0 is the pit, 1-3 are meat probes.
PROBE_SLOTS = 4

SIGNAL_UPDATE = "flameboss_update_{}"
EVENT_ALERT = "flameboss_alert"
