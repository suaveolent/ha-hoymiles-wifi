from datetime import timedelta

DOMAIN = "hoymiles_wifi"
NAME = "Hoymiles HMS-XXXXW-T2"
DOMAIN = "hoymiles_wifi"
DOMAIN_DATA = f"{DOMAIN}_data"
VERSION = "0.0.1"

ISSUE_URL = "https://github.com/suaveolent/ha-hoymiles-wifi/issues"

CONF_UPDATE_INTERVAL = "update_interval"

DEFAULT_UPDATE_INTERVAL = timedelta(seconds=30)
MIN_UPDATE_INTERVAL = timedelta(seconds=30)


# Platforms
SENSOR = "sensor"
PLATFORMS = [SENSOR]

STARTUP_MESSAGE = f"""
-------------------------------------------------------------------
{NAME}
Version: {VERSION}
This is a custom integration!
If you have any issues with this you need to open an issue here:
{ISSUE_URL}
-------------------------------------------------------------------
"""
