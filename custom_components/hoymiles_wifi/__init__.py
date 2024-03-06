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
    CONF_DTU_SERIAL_NUMBER,
    CONF_INVERTERS,
    CONF_PORTS,
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

        real_data = await inverter.async_get_real_data_new()
        if(real_data is None):
            _LOGGER.error("Could not retrieve real data information data from inverter: %s. Please ensure inverter is available!", host)
            return False

        dtu_sn = real_data.device_serial_number

        inverters = []

        for sgs_data in real_data.sgs_data:
            inverter_serial = generate_inverter_serial_number(sgs_data.serial_number)
            inverters.append(inverter_serial)

        ports = []
        for pv_data in real_data.pv_data:
            inverter_serial = generate_inverter_serial_number(pv_data.serial_number)
            port_number = pv_data.port_number
            ports.append({
                "inverter_serial_number": inverter_serial,
                "port_number": port_number
            })

        new[CONF_DTU_SERIAL_NUMBER] = dtu_sn
        new[CONF_INVERTERS] = inverters
        new[CONF_PORTS] = ports

        # Update the config entry with the new data
        hass.config_entries.async_update_entry(config_entry, data=new, version=2)

    _LOGGER.info("Migration of entry %s to version %s successful", config_entry.entry_id, CURRENT_VERSION)
    return True

