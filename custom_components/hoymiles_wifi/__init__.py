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
    DEFAULT_DIAGNOSTIC_UPDATE_INTERVAL_SECONDS,
    DOMAIN,
    HASS_CONFIG_COORDINATOR,
    HASS_DATA_COORDINATOR,
    HASS_DATA_UNSUB_OPTIONS_UPDATE_LISTENER,
    HASS_INVERTER,
)
from .coordinator import (
    HoymilesConfigUpdateCoordinatorInverter,
    HoymilesRealDataUpdateCoordinatorInverter,
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

    data_coordinator = HoymilesRealDataUpdateCoordinatorInverter(hass, inverter=inverter, entry=entry, update_interval=update_interval)
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

