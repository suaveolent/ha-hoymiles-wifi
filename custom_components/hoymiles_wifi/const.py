DOMAIN = "hoymiles_wifi"
NAME = "Hoymiles HMS-XXXXW-T2"
DOMAIN = "hoymiles_wifi"
DOMAIN_DATA = f"{DOMAIN}_data"
VERSION = "0.0.7"

ISSUE_URL = "https://github.com/suaveolent/ha-hoymiles-wifi/issues"

CONF_UPDATE_INTERVAL = "update_interval"
CONF_SENSOR_PREFIX = "sensor_prefix"

DEFAULT_UPDATE_INTERVAL_SECONDS = 35
MIN_UPDATE_INTERVAL_SECONDS = 35

DEFAULT_DIAGNOSTIC_UPDATE_INTERVAL_SECONDS = 60

HASS_DATA_COORDINATOR = "data_coordinator"
HASS_CONFIG_COORDINATOR = "config_coordinator"
HASS_DATA_UNSUB_OPTIONS_UPDATE_LISTENER = "unsub_options_update_listener"

CONVERSION_HEX = "hex"

STARTUP_MESSAGE = f"""

-------------------------------------------------------------------
{NAME}
Version: {VERSION}
This is a custom integration!
If you have any issues with this you need to open an issue here:
{ISSUE_URL}
-------------------------------------------------------------------
"""
