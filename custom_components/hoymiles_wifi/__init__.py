"""Platform for retrieving values of a Hoymiles inverter."""

from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv, device_registry as dr
from homeassistant.helpers.device_registry import DeviceEntry
from homeassistant.helpers.service import SupportsResponse
from homeassistant.helpers.typing import ConfigType
from hoymiles_wifi.dtu import DTU
from hoymiles_wifi.hoymiles import get_dtu_model_name
import voluptuous as vol

from .const import (
    CONF_DTU_SERIAL_NUMBER,
    CONF_ENC_RAND,
    CONF_HYBRID_INVERTERS,
    CONF_INVERTERS,
    CONF_IS_ENCRYPTED,
    CONF_METERS,
    CONF_PORTS,
    CONF_THREE_PHASE_INVERTERS,
    CONF_TIMEOUT,
    CONF_UPDATE_INTERVAL,
    CONFIG_VERSION,
    DEFAULT_APP_INFO_UPDATE_INTERVAL_SECONDS,
    DEFAULT_CONFIG_UPDATE_INTERVAL_SECONDS,
    DEFAULT_TIMEOUT_SECONDS,
    DOMAIN,
    HASS_APP_INFO_COORDINATOR,
    HASS_CONFIG_COORDINATOR,
    HASS_DATA_COORDINATOR,
    HASS_DTU,
    HASS_ENERGY_STORAGE_CONFIG_COORDINATOR,
    HASS_ENERGY_STORAGE_DATA_COORDINATOR,
)
from .coordinator import (
    HoymilesAppInfoUpdateCoordinator,
    HoymilesConfigUpdateCoordinator,
    HoymilesEnergyStorageConfigUpdateCoordinator,
    HoymilesEnergyStorageUpdateCoordinator,
    HoymilesLiveDataUpdateCoordinator,
    HoymilesRealDataUpdateCoordinator,
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
    dtu_serial_number = str(config_entry.data[CONF_DTU_SERIAL_NUMBER])
    registry = dr.async_get(hass)
    previously_configured = any(
        (DOMAIN, dtu_serial_number) in device.identifiers
        for device in dr.async_entries_for_config_entry(registry, config_entry.entry_id)
    )

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

        for coordinator in (data_coordinator, config_coordinator):
            coordinator.set_encryption_resync_callback(
                app_info_update_coordinator.async_resync_encryption
            )

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
        energy_storage_config_coordinator = (
            HoymilesEnergyStorageConfigUpdateCoordinator(
                hass=hass,
                dtu=dtu,
                config_entry=config_entry,
                update_interval=timedelta(
                    seconds=DEFAULT_CONFIG_UPDATE_INTERVAL_SECONDS
                ),
                dtu_serial_number=config_entry.data[CONF_DTU_SERIAL_NUMBER],
                inverters=hybrid_inverters,
            )
        )
        hass_data[HASS_ENERGY_STORAGE_CONFIG_COORDINATOR] = (
            energy_storage_config_coordinator
        )

    if single_phase_inverters or three_phase_inverters or meters:
        await app_info_update_coordinator.async_refresh()
        await _async_refresh_live_data(data_coordinator, previously_configured)
        await config_coordinator.async_refresh()
        if data_coordinator.last_update_success:
            _async_update_config_polling(config_coordinator)
        else:
            config_coordinator.update_interval = None
            _async_retry_metadata_when_online(
                hass,
                config_entry,
                data_coordinator,
                config_coordinator,
                app_info_update_coordinator,
            )
    if hybrid_inverters:
        await _async_refresh_live_data(
            energy_storage_data_coordinator, previously_configured
        )
        await energy_storage_config_coordinator.async_refresh()
        if not energy_storage_data_coordinator.last_update_success:
            energy_storage_config_coordinator.update_interval = None
            _async_retry_metadata_when_online(
                hass,
                config_entry,
                energy_storage_data_coordinator,
                energy_storage_config_coordinator,
            )

    _LOGGER.debug("  hass_data: %s", hass_data)
    _LOGGER.debug("  config_entry_id: %s", config_entry.entry_id)

    hass.data[DOMAIN][config_entry.entry_id] = hass_data

    # Register the DTU before platforms register devices connected through it.
    registry.async_get_or_create(
        config_entry_id=config_entry.entry_id,
        identifiers={(DOMAIN, dtu_serial_number)},
        translation_key="dtu",
        manufacturer="Hoymiles",
        serial_number=dtu_serial_number.upper(),
        model=get_dtu_model_name(dtu_serial_number),
    )
    await hass.config_entries.async_forward_entry_setups(config_entry, PLATFORMS)

    if hybrid_inverters:
        hass.services.async_register(
            domain=DOMAIN,
            service="set_bms_mode",
            service_func=async_handle_set_bms_mode,
            schema=SET_BMS_SCHEMA,
            supports_response=SupportsResponse.NONE,
        )
        _LOGGER.debug("Service set_bms_mode registered")

    return True


async def _async_refresh_live_data(
    coordinator: HoymilesLiveDataUpdateCoordinator, previously_configured: bool
) -> None:
    """Require live data only before the DTU has ever been registered successfully."""
    if previously_configured:
        await coordinator.async_refresh()
    else:
        await coordinator.async_config_entry_first_refresh()


@callback
def _async_update_config_polling(coordinator: HoymilesConfigUpdateCoordinator) -> None:
    """Poll supported configuration commands after a reachable DTU is probed."""
    if coordinator.last_update_success:
        coordinator.update_interval = timedelta(
            seconds=DEFAULT_CONFIG_UPDATE_INTERVAL_SECONDS
        )
    else:
        coordinator.update_interval = None
        _LOGGER.info(
            "DTU %s did not provide configuration; disabling configuration polling until the integration is reloaded",
            coordinator.get_dtu().host,
        )


def _async_retry_metadata_when_online(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    live_coordinator: HoymilesLiveDataUpdateCoordinator,
    config_coordinator: HoymilesLiveDataUpdateCoordinator,
    app_info_coordinator: HoymilesAppInfoUpdateCoordinator | None = None,
) -> None:
    """Retry startup metadata once live polling recovers from an offline startup."""

    async def refresh_metadata() -> None:
        """Read current metadata and restore its supported polling interval."""
        if app_info_coordinator is not None:
            await app_info_coordinator.async_refresh()
        config_coordinator.update_interval = timedelta(
            seconds=DEFAULT_CONFIG_UPDATE_INTERVAL_SECONDS
        )
        await config_coordinator.async_refresh()
        if isinstance(config_coordinator, HoymilesConfigUpdateCoordinator):
            _async_update_config_polling(config_coordinator)

    @callback
    def refresh_when_online() -> None:
        """Wait for an actual successful reading before retrying metadata."""
        if not live_coordinator.last_update_success or live_coordinator.data_is_stale:
            return
        cancel_retry()
        config_entry.async_create_background_task(
            hass, refresh_metadata(), "Refresh Hoymiles metadata after offline startup"
        )

    remove_listener = live_coordinator.async_add_listener(refresh_when_online)

    @callback
    def cancel_retry() -> None:
        """Remove the one-shot listener at most once, including during unload."""
        nonlocal remove_listener
        if remove_listener is not None:
            remove_listener()
            remove_listener = None

    config_entry.async_on_unload(cancel_retry)


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
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
