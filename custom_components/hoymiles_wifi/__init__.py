"""Platform for retrieving values of a Hoymiles inverter."""

import asyncio
from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, Platform
from homeassistant.core import Config, HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntry
from hoymiles_wifi.dtu import DTU

from .const import (
    CONF_DTU_SERIAL_NUMBER,
    CONF_INVERTERS,
    CONF_PORTS,
    CONF_UPDATE_INTERVAL,
    CONFIG_VERSION,
    DEFAULT_APP_INFO_UPDATE_INTERVAL_SECONDS,
    DEFAULT_CONFIG_UPDATE_INTERVAL_SECONDS,
    DOMAIN,
    HASS_APP_INFO_COORDINATOR,
    HASS_CONFIG_COORDINATOR,
    HASS_DATA_COORDINATOR,
    HASS_DTU,
)
from .coordinator import (
    HoymilesAppInfoUpdateCoordinator,
    HoymilesConfigUpdateCoordinator,
    HoymilesRealDataUpdateCoordinator,
)
from .error import CannotConnect
from .util import async_get_config_entry_data_for_host

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

    dtu = DTU(host)

    hass_data[HASS_DTU] = dtu

    data_coordinator = HoymilesRealDataUpdateCoordinator(
        hass, dtu=dtu, entry=entry, update_interval=update_interval
    )
    hass_data[HASS_DATA_COORDINATOR] = data_coordinator

    config_update_interval = timedelta(seconds=DEFAULT_CONFIG_UPDATE_INTERVAL_SECONDS)
    config_coordinator = HoymilesConfigUpdateCoordinator(
        hass, dtu=dtu, entry=entry, update_interval=config_update_interval
    )
    hass_data[HASS_CONFIG_COORDINATOR] = config_coordinator

    app_info_update_interval = timedelta(
        seconds=DEFAULT_APP_INFO_UPDATE_INTERVAL_SECONDS
    )
    app_info_update_coordinator = HoymilesAppInfoUpdateCoordinator(
        hass, dtu=dtu, entry=entry, update_interval=app_info_update_interval
    )
    hass_data[HASS_APP_INFO_COORDINATOR] = app_info_update_coordinator

    hass.data[DOMAIN][entry.entry_id] = hass_data

    await data_coordinator.async_config_entry_first_refresh()
    await asyncio.sleep(2)
    await config_coordinator.async_config_entry_first_refresh()
    await asyncio.sleep(2)
    await app_info_update_coordinator.async_config_entry_first_refresh()

    return True


async def async_remove_config_entry_device(
    hass: HomeAssistant, config_entry: ConfigEntry, device_entry: DeviceEntry
) -> bool:
    """Remove a config entry from a device."""
    return True


async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Migrate old entry data to the new entry schema."""

    data = config_entry.data.copy()

    current_version = data.get("version", 1)

    if current_version == 1:
        _LOGGER.info(
            "Migrating entry %s to version %s", config_entry.entry_id, CONFIG_VERSION
        )
        new = {**config_entry.data}

        host = config_entry.data.get(CONF_HOST)

        try:
            dtu_sn, inverters, ports = await async_get_config_entry_data_for_host(host)
        except CannotConnect:
            _LOGGER.error(
                "Could not retrieve real data information data from inverter: %s. Please ensure inverter is available!",
                host,
            )
            return False

        new[CONF_DTU_SERIAL_NUMBER] = dtu_sn
        new[CONF_INVERTERS] = inverters
        new[CONF_PORTS] = ports

        hass.config_entries.async_update_entry(config_entry, data=new, version=2)
        _LOGGER.info(
            "Migration of entry %s to version %s successful",
            config_entry.entry_id,
            CONFIG_VERSION,
        )

    return True
