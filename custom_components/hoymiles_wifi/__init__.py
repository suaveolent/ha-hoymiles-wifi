"""Platform for retrieving values of a Hoymiles inverter."""
import asyncio
from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, Platform
from homeassistant.core import Config, HomeAssistant
from hoymiles_wifi.inverter import Inverter
from hoymiles_wifi.utils import generate_inverter_serial_number

from .const import (
    CONF_DEVICE_NUMBERS,
    CONF_DTU_SERIAL_NUMBER,
    CONF_INERTER_SERIAL_NUMBERS,
    CONF_PV_NUMBERS,
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

CURRENT_VERSION = 2

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


async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Migrate old entry data to the new entry schema."""

    _LOGGER.info("Migrating entry %s to version %s", config_entry.entry_id, CURRENT_VERSION)

    # Get the current data from the config entry
    data = config_entry.data.copy()

    # Check the version of the existing data
    current_version = data.get("version", 1)

    # Perform migrations based on the version
    if current_version == 1:
        _LOGGER.info("Migrating from version 1 to version 2")

        new = {**config_entry.data}

        host = config_entry.data.get(CONF_HOST)

        inverter = Inverter(host)
        app_info_data = await inverter.async_app_information_data()
        if(app_info_data is None):
            _LOGGER.error("Could not retrieve app information data from inverter: %s. Please ensure inverter is available!", host)
            return False

        device_numbers = app_info_data.device_number
        pv_numbers = app_info_data.pv_number
        dtu_sn = app_info_data.dtu_serial_number

        inverter_serials = []

        for pv_info in app_info_data.pv_info:
            inverter_serials.append(generate_inverter_serial_number(pv_info.pv_serial_number))

        new[CONF_DTU_SERIAL_NUMBER] = dtu_sn
        new[CONF_INERTER_SERIAL_NUMBERS] = inverter_serials
        new[CONF_DEVICE_NUMBERS] = device_numbers
        new[CONF_PV_NUMBERS] = pv_numbers


    # Update the config entry with the new data
        hass.config_entries.async_update_entry(config_entry, data=new, version=2)

    _LOGGER.info("Migration of entry %s to version %s successful", config_entry.entry_id, CURRENT_VERSION)
    return True

