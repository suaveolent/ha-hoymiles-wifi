from datetime import timedelta

DOMAIN = "hoymiles_wifi"

CONF_UPDATE_INTERVAL = "update_interval"

DEFAULT_UPDATE_INTERVAL = timedelta(seconds=30)
MIN_UPDATE_INTERVAL = timedelta(seconds=30)


# Platforms
SENSOR = "sensor"
PLATFORMS = [SENSOR]
