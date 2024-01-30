"""Platform for retrieving values of a Hoymiles inverter."""
import asyncio
from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, Platform
from homeassistant.core import Config, HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from hoymiles_wifi.inverter import Inverter

from .const import (
    CONF_UPDATE_INTERVAL,
    DEFAULT_DIAGNOSTIC_UPDATE_INTERVAL_SECONDS,
    DOMAIN,
    HASS_CONFIG_COORDINATOR,
    HASS_DATA_COORDINATOR,
    HASS_DATA_UNSUB_OPTIONS_UPDATE_LISTENER,
    HASS_INVERTER,
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

    data_coordinator = HoymilesDataUpdateCoordinatorInverter(hass, inverter=inverter, entry=entry, update_interval=update_interval)
    hass_data[HASS_DATA_COORDINATOR] = data_coordinator

    config_update_interval = timedelta(seconds=DEFAULT_DIAGNOSTIC_UPDATE_INTERVAL_SECONDS)
    config_coordinator = HoymilesConfigUpdateCoordinatorInverter(hass, inverter=inverter, entry=entry, update_interval=config_update_interval)
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
            "async_unload_entry call to hass.config_entries.async_forward_entry_unload returned False"
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


class HoymilesCoordinatorEntity(DataUpdateCoordinator):
    """Base coordinator entity for Hoymiles integration."""

    def __init__(self, hass: HomeAssistant, inverter: Inverter, entry: ConfigEntry, update_interval: timedelta) -> None:
        """Initialize the HoymilesCoordinatorEntity."""
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
        """Get the inverter object."""
        return self._inverter



class HoymilesDataUpdateCoordinatorInverter(HoymilesCoordinatorEntity):
    """Data coordinator entity for Hoymiles integration."""

    async def _async_update_data(self):
        """Update data via library."""
        _LOGGER.debug("Hoymiles data coordinator update")

        response = self._inverter.get_real_data_new()

        if not self._entities_added:
            self._hass.async_add_job(
                self._hass.config_entries.async_forward_entry_setups(self._entry, PLATFORMS)
            )
            self._entities_added = True

        if response:
            return response
        else:
            _LOGGER.debug("Unable to retrieve real data new. Inverter might be offline.")
            return None



class HoymilesConfigUpdateCoordinatorInverter(HoymilesCoordinatorEntity):
    """Config coordinator entity for Hoymiles integration."""

    async def _async_update_data(self):
        """Update data via library."""
        _LOGGER.debug("Hoymiles data coordinator update")

        response = self._inverter.get_config()

        if response:
            return response
        else:
            _LOGGER.debug("Unable to retrieve real data new. Inverter might be offline.")
            return None



