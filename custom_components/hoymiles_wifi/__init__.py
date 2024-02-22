"""Platform for retrieving values of a Hoymiles inverter."""
import asyncio
from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, Platform
from homeassistant.core import Config, HomeAssistant
from hoymiles_wifi.inverter import Inverter

from .const import (
    CONF_UPDATE_INTERVAL,
    DEFAULT_APP_INFO_UPDATE_INTERVAL_SECONDS,
    DEFAULT_CONFIG_UPDATE_INTERVAL_SECONDS,
    DOMAIN,
    HASS_APP_INFO_COORDINATOR,
    HASS_CONFIG_COORDINATOR,
    HASS_DATA_COORDINATOR,
    HASS_INVERTER,
)
from .coordinator import (
    HoymilesAppInfoUpdateCoordinator,
    HoymilesConfigUpdateCoordinator,
    HoymilesRealDataUpdateCoordinator,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR, Platform.NUMBER, Platform.BINARY_SENSOR, Platform.BUTTON]

async def async_setup(hass: HomeAssistant, config: Config):
    """Set up this integration using YAML is not supported."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Set up this integration using UI."""

    hass.data.setdefault(DOMAIN, {})

    hass_data = dict(entry.data)

    host = entry.data.get(CONF_HOST)
    update_interval = timedelta(seconds=entry.data.get(CONF_UPDATE_INTERVAL))

    inverter = Inverter(host)

    hass_data[HASS_INVERTER] = inverter

    data_coordinator = HoymilesRealDataUpdateCoordinator(hass, inverter=inverter, entry=entry, update_interval=update_interval)
    hass_data[HASS_DATA_COORDINATOR] = data_coordinator

    config_update_interval = timedelta(seconds=DEFAULT_CONFIG_UPDATE_INTERVAL_SECONDS)
    config_coordinator = HoymilesConfigUpdateCoordinator(hass, inverter=inverter, entry=entry, update_interval=config_update_interval)
    hass_data[HASS_CONFIG_COORDINATOR] = config_coordinator

    app_info_update_interval = timedelta(seconds=DEFAULT_APP_INFO_UPDATE_INTERVAL_SECONDS)
    app_info_update_coordinator = HoymilesAppInfoUpdateCoordinator(hass, inverter=inverter, entry=entry, update_interval=app_info_update_interval)
    hass_data[HASS_APP_INFO_COORDINATOR] = app_info_update_coordinator

    hass.data[DOMAIN][entry.entry_id] = hass_data

    await data_coordinator.async_config_entry_first_refresh()
    await asyncio.sleep(5)
    await config_coordinator.async_config_entry_first_refresh()
    await asyncio.sleep(5)
    await app_info_update_coordinator.async_config_entry_first_refresh()

    return True

