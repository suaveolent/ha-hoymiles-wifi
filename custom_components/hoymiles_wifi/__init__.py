"""Platform for retrieving the current power of a PV system."""
import logging
from datetime import timedelta

from hoymiles_wifi.inverter import Inverter

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Config
from homeassistant.core import HomeAssistant
from homeassistant.components.sensor import PLATFORM_SCHEMA
from homeassistant.const import CONF_HOST
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    CONF_UPDATE_INTERVAL,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    PLATFORMS,
    STARTUP_MESSAGE,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: Config):
    """Set up this integration using YAML is not supported."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Set up this integration using UI."""

    if hass.data.get(DOMAIN) is None:
        hass.data.setdefault(DOMAIN, {})
        _LOGGER.info(STARTUP_MESSAGE)

    host = entry.data.get(CONF_HOST)
    update_interval = timedelta(seconds=entry.data.get(CONF_UPDATE_INTERVAL))

    inverter = Inverter(host)

    coordinator = HoymilesDataUpdatecoordinatorInverter(hass, inverter=inverter, update_interval=update_interval, entry=entry)
    hass.data[DOMAIN][entry.entry_id] = coordinator

    await coordinator.async_config_entry_first_refresh()

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Handle removal of an entry."""

    # _LOGGER.debug("Unload entry")
    # unloaded = all(
    #     await asyncio.gather(
    #         *[
    #             hass.config_entries.async_forward_entry_unload(entry, platform)
    #             for platform in PLATFORMS
    #         ]
    #     )
    # )
    # if unloaded:
    #     coordinator = hass.data[DOMAIN].pop(entry.entry_id)
    #     coordinator.unsub()

    return True  # unloaded


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry."""
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)

    
class HoymilesDataUpdatecoordinatorInverter(DataUpdateCoordinator):
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


    async def _async_update_data(self):
        """Update data via library."""
        _LOGGER.debug("Hoymiles data coordinator update")

        response = self._inverter.update_state()

        if not self._entities_added:
            for platform in PLATFORMS:
                self._hass.async_add_job(
                    self._hass.config_entries.async_forward_entry_setup(
                        self._entry, platform
                    )
                )
            self._entities_added = True

        if response:
            _LOGGER.debug(f"Inverter State: {response}")
            return response
        else:
            _LOGGER.debug("Unable to retrieve inverter state. Inverter might be offline.")
            return None




