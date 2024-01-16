"""Platform for retrieving the current power of a PV system."""
import logging
import asyncio
from datetime import timedelta

from hoymiles_wifi.inverter import Inverter

import voluptuous as vol

from homeassistant.core import (
    HomeAssistant,
    Config
) 

from homeassistant.config_entries import ConfigEntry
from homeassistant.components.sensor import PLATFORM_SCHEMA
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from homeassistant.const import (
    Platform,
    CONF_HOST
)

from .const import (
    CONF_UPDATE_INTERVAL,
    DOMAIN,
    STARTUP_MESSAGE,
    HASS_DATA_COORDINATOR,
    HASS_CONFIG_COORDINATOR,
    HASS_DATA_UNSUB_OPTIONS_UPDATE_LISTENER,
    DEFAULT_DIAGNOSTIC_UPDATE_INTERVAL_SECONDS,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR, Platform.NUMBER]

async def async_setup(hass: HomeAssistant, config: Config):
    """Set up this integration using YAML is not supported."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Set up this integration using UI."""

    if hass.data.get(DOMAIN) is None:
        hass.data.setdefault(DOMAIN, {})
        _LOGGER.info(STARTUP_MESSAGE)

    hass_data = dict(entry.data)

    host = entry.data.get(CONF_HOST)
    update_interval = timedelta(seconds=entry.data.get(CONF_UPDATE_INTERVAL))

    inverter = Inverter(host)

    data_coordinator = HoymilesDataUpdateCoordinatorInverter(hass, inverter=inverter, update_interval=update_interval, entry=entry)
    hass_data[HASS_DATA_COORDINATOR] = data_coordinator

    config_update_interval = timedelta(seconds=DEFAULT_DIAGNOSTIC_UPDATE_INTERVAL_SECONDS)
    config_coordinator = HoymilesConfigUpdateCoordinatorInverter(hass, inverter=inverter, update_interval=config_update_interval, entry=entry)
    hass_data[HASS_CONFIG_COORDINATOR] = config_coordinator

    
    # Registers update listener to update config entry when options are updated.
    unsub_options_update_listener = entry.add_update_listener(options_update_listener)
    hass_data[HASS_DATA_UNSUB_OPTIONS_UPDATE_LISTENER] = unsub_options_update_listener
    
    hass.data[DOMAIN][entry.entry_id] = hass_data

    await data_coordinator.async_config_entry_first_refresh()
    await config_coordinator.async_config_entry_first_refresh()

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Handle removal of an entry."""

    _LOGGER.debug("Unload entry")
    unloaded = all(
        await asyncio.gather(
            *[
                hass.config_entries.async_forward_entry_unload(entry, platform)
                for platform in PLATFORMS
            ]
        )
    )

    # Remove options_update_listener.
    hass.data[DOMAIN][entry.entry_id][HASS_DATA_UNSUB_OPTIONS_UPDATE_LISTENER]()

    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id)
    else:
        _LOGGER.error(
            f"async_unload_entry call to hass.config_entries.async_forward_entry_unload returned False"
        )
        return False

    return True  # unloaded

async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry."""
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)

async def options_update_listener(hass: HomeAssistant, config_entry: ConfigEntry) -> None:
    """Handle options update."""
    _LOGGER.error("Options update called!")
    await hass.config_entries.async_reload(config_entry.entry_id)

    
class HoymilesDataUpdateCoordinatorInverter(DataUpdateCoordinator):
    """Class to manage fetching data from the API."""

    def __init__(self, hass: HomeAssistant, inverter: Inverter, update_interval, entry) -> None:
        """Initialize."""
        self._inverter = inverter
        self._entities_added = False
        self._hass = hass
        self._entry = entry

        _LOGGER.debug(
            "Setup entry with update interval %s. IP: %s",
            update_interval,
            entry.data.get(CONF_HOST),
        )

        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=update_interval)


    def get_inverter(self):
        return self._inverter

    async def _async_update_data(self):
        """Update data via library."""
        _LOGGER.debug("Hoymiles data coordinator update")

        response = self._inverter.get_real_data_new()

        if not self._entities_added:
            for platform in PLATFORMS:
                self._hass.async_add_job(
                    self._hass.config_entries.async_forward_entry_setup(
                        self._entry, platform
                    )
                )
            self._entities_added = True

        if response:
            _LOGGER.debug(f"Inverter Real data: {response}")
            return response
        else:
            _LOGGER.debug("Unable to retrieve real data new. Inverter might be offline.")
            return None
        


class HoymilesConfigUpdateCoordinatorInverter(DataUpdateCoordinator):
    """Class to manage fetching data from the API."""

    def __init__(self, hass: HomeAssistant, inverter: Inverter, update_interval, entry) -> None:
        """Initialize."""
        self._inverter = inverter
        self._hass = hass
        self._entry = entry

        _LOGGER.debug(
            "Setup entry with update interval %s. IP: %s",
            update_interval,
            entry.data.get(CONF_HOST),
        )

        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=update_interval)

    def get_inverter(self):
        return self._inverter

    async def _async_update_data(self):
        """Update data via library."""
        _LOGGER.debug("Hoymiles data coordinator update")

        response = self._inverter.get_config()

        if response:
            _LOGGER.debug(f"Inverter Config data: {response}")
            return response
        else:
            _LOGGER.debug("Unable to retrieve real data new. Inverter might be offline.")
            return None
        


