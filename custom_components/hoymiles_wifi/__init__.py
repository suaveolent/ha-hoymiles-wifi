"""Platform for retrieving values of a Hoymiles inverter."""

from datetime import timedelta
import logging
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntry
from homeassistant.helpers.typing import ConfigType
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.service import SupportsResponse
from hoymiles_wifi.dtu import DTU

from .const import (
    CONF_DTU_SERIAL_NUMBER,
    CONF_HYBRID_INVERTERS,
    CONF_INVERTERS,
    CONF_METERS,
    CONF_PORTS,
    CONF_THREE_PHASE_INVERTERS,
    CONF_TIMEOUT,
    CONF_UPDATE_INTERVAL,
    CONFIG_VERSION,
    CONF_IS_ENCRYPTED,
    CONF_ENC_RAND,
    DEFAULT_APP_INFO_UPDATE_INTERVAL_SECONDS,
    DEFAULT_CONFIG_UPDATE_INTERVAL_SECONDS,
    DEFAULT_TIMEOUT_SECONDS,
    DOMAIN,
    HASS_APP_INFO_COORDINATOR,
    HASS_CONFIG_COORDINATOR,
    HASS_DATA_COORDINATOR,
    HASS_DTU,
    HASS_ENERGY_STORAGE_DATA_COORDINATOR,
)
from .coordinator import (
    HoymilesAppInfoUpdateCoordinator,
    HoymilesConfigUpdateCoordinator,
    HoymilesRealDataUpdateCoordinator,
    HoymilesEnergyStorageUpdateCoordinator,
)
from .error import CannotConnect
from .services import async_handle_set_bms_mode
from .util import async_get_config_entry_data_for_host

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR, Platform.NUMBER, Platform.BINARY_SENSOR, Platform.BUTTON]

SET_BMS_SCHEMA = vol.Schema(
    {
        vol.Required("bms_mode"): vol.In(
            (
                "self_use",
                "economic",
                "backup_power",
                "pure_off_grid",
                "forced_charging",
                "forced_discharge",
                "peak_shaving",
                "time_of_use",
            )
        ),
        vol.Required("rev_soc"): vol.All(vol.Coerce(int), vol.Range(min=0, max=100)),
        vol.Optional("max_power"): vol.All(vol.Coerce(int), vol.Range(min=0)),
        vol.Optional("peak_soc"): vol.All(vol.Coerce(int), vol.Range(min=0, max=100)),
        vol.Optional("peak_meter_power"): vol.All(vol.Coerce(int), vol.Range(min=0)),
        vol.Optional("time_settings"): str,
        vol.Optional("time_periods"): str,
        vol.Optional("device_id"): cv.ensure_list,
    }
)


async def async_setup(hass: HomeAssistant, config: ConfigType):
    """Set up this integration using YAML is not supported."""
    return True


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry):
    """Set up this integration using UI."""

    hass.data.setdefault(DOMAIN, {})

    hass_data = dict(config_entry.data)

    host = config_entry.data.get(CONF_HOST)
    update_interval = timedelta(seconds=config_entry.data.get(CONF_UPDATE_INTERVAL))
    single_phase_inverters = config_entry.data[CONF_INVERTERS]
    three_phase_inverters = config_entry.data.get(CONF_THREE_PHASE_INVERTERS, [])
    hybrid_inverters = config_entry.data.get(CONF_HYBRID_INVERTERS, [])
    meters = config_entry.data.get(CONF_METERS, [])
    is_encrypted = config_entry.data.get(CONF_IS_ENCRYPTED, False)
    enc_rand = config_entry.data.get(CONF_ENC_RAND, None)
    timeout = config_entry.data.get(CONF_TIMEOUT, DEFAULT_TIMEOUT_SECONDS)

    if is_encrypted:
        dtu = DTU(
            host,
            is_encrypted=is_encrypted,
            enc_rand=bytes.fromhex(enc_rand),
            timeout=timeout,
        )
    else:
        dtu = DTU(host, timeout=timeout)

    hass_data[HASS_DTU] = dtu

    if single_phase_inverters or three_phase_inverters or meters:
        data_coordinator = HoymilesRealDataUpdateCoordinator(
            hass, dtu=dtu, config_entry=config_entry, update_interval=update_interval
        )
        hass_data[HASS_DATA_COORDINATOR] = data_coordinator

        config_update_interval = timedelta(
            seconds=DEFAULT_CONFIG_UPDATE_INTERVAL_SECONDS
        )
        config_coordinator = HoymilesConfigUpdateCoordinator(
            hass=hass,
            dtu=dtu,
            config_entry=config_entry,
            update_interval=config_update_interval,
        )
        hass_data[HASS_CONFIG_COORDINATOR] = config_coordinator

        app_info_update_interval = timedelta(
            seconds=DEFAULT_APP_INFO_UPDATE_INTERVAL_SECONDS
        )
        app_info_update_coordinator = HoymilesAppInfoUpdateCoordinator(
            hass=hass,
            dtu=dtu,
            config_entry=config_entry,
            update_interval=app_info_update_interval,
        )
        hass_data[HASS_APP_INFO_COORDINATOR] = app_info_update_coordinator

    if hybrid_inverters:
        energy_storage_data_coordinator = HoymilesEnergyStorageUpdateCoordinator(
            hass=hass,
            dtu=dtu,
            config_entry=config_entry,
            update_interval=update_interval,
            dtu_serial_number=config_entry.data[CONF_DTU_SERIAL_NUMBER],
            inverters=hybrid_inverters,
        )

        hass_data[HASS_ENERGY_STORAGE_DATA_COORDINATOR] = (
            energy_storage_data_coordinator
        )

    _LOGGER.debug(f"  hass_data: {hass_data}")  # --- IGNORE ---
    _LOGGER.debug(f"  config_entry_id: {config_entry.entry_id}")

    hass.data[DOMAIN][config_entry.entry_id] = hass_data
    await hass.config_entries.async_forward_entry_setups(config_entry, PLATFORMS)

    if single_phase_inverters or three_phase_inverters or meters:
        await data_coordinator.async_config_entry_first_refresh()
        await config_coordinator.async_config_entry_first_refresh()
        await app_info_update_coordinator.async_config_entry_first_refresh()
    if hybrid_inverters:
        await energy_storage_data_coordinator.async_config_entry_first_refresh()
        hass.services.async_register(
            domain=DOMAIN,
            service="set_bms_mode",
            service_func=async_handle_set_bms_mode,
            schema=SET_BMS_SCHEMA,
            supports_response=SupportsResponse.NONE,
        )
        _LOGGER.debug("Service set_bms_mode registered")

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

    if current_version != CONFIG_VERSION:
        _LOGGER.info(
            "Migrating entry %s to version %s", config_entry.entry_id, CONFIG_VERSION
        )
        new = {**config_entry.data}

        host = config_entry.data.get(CONF_HOST)
        try:
            (
                dtu_sn,
                single_phase_inverters,
                three_phase_inverters,
                ports,
                meters,
                hybrid_inverters,
                is_encrypted,
                enc_rand,
            ) = await async_get_config_entry_data_for_host(host)
        except CannotConnect:
            _LOGGER.error(
                "Could not retrieve real data information data from inverter: %s. Please ensure inverter is available!",
                host,
            )
            return False

        new[CONF_DTU_SERIAL_NUMBER] = dtu_sn
        new[CONF_INVERTERS] = single_phase_inverters
        new[CONF_THREE_PHASE_INVERTERS] = three_phase_inverters
        new[CONF_PORTS] = ports
        new[CONF_METERS] = meters
        new[CONF_HYBRID_INVERTERS] = hybrid_inverters
        new[CONF_IS_ENCRYPTED] = is_encrypted
        new[CONF_ENC_RAND] = enc_rand

        hass.config_entries.async_update_entry(
            config_entry, data=new, version=CONFIG_VERSION
        )
        _LOGGER.info(
            "Migration of entry %s to version %s successful",
            config_entry.entry_id,
            CONFIG_VERSION,
        )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    return unload_ok
