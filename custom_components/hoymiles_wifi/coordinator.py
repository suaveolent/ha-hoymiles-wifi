"""Coordinator for Hoymiles integration."""

from collections.abc import Awaitable, Callable
from datetime import timedelta
from enum import Enum
import logging
import math
from time import monotonic

import homeassistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, Platform
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util
from hoymiles_wifi.const import (
    MAX_POWER_LIMIT,
    MAX_TEMPORARY_POWER_LIMIT_WATTS,
    MIN_TEMPORARY_POWER_LIMIT_WATTS,
)
from hoymiles_wifi.dtu import DTU, NetworkState
from hoymiles_wifi.hoymiles import (
    DTUType,
    generate_inverter_serial_number,
    get_dtu_model_type,
)

from .const import (
    CONF_CLOUD_PAUSE,
    CONF_DTU_SERIAL_NUMBER,
    CONF_INVERTERS,
    CONF_THREE_PHASE_INVERTERS,
    DEFAULT_CLOUD_PAUSE_SECONDS,
    DOMAIN,
    ENC_RAND_RESYNC_MIN_INTERVAL_SECONDS,
)
from .util import async_check_and_update_enc_rand, is_encrypted_dtu

_LOGGER = logging.getLogger(__name__)
LIVE_DATA_GRACE_SECONDS = 180

PLATFORMS = [Platform.SENSOR, Platform.NUMBER, Platform.BINARY_SENSOR, Platform.BUTTON]


class HoymilesDataUpdateCoordinator(DataUpdateCoordinator):
    """Base data update coordinator for Hoymiles integration."""

    def __init__(
        self,
        hass: homeassistant,
        dtu: DTU,
        config_entry: ConfigEntry,
        update_interval: timedelta,
    ) -> None:
        """Initialize the HoymilesCoordinatorEntity."""
        self._dtu = dtu
        self._hass = hass
        self._config_entry = config_entry

        _LOGGER.debug(
            "Setup entry with update interval %s. IP: %s",
            update_interval,
            config_entry.data.get(CONF_HOST),
        )

        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=update_interval)

    def get_dtu(self) -> DTU:
        """Get the DTU object."""
        return self._dtu


class HoymilesLiveDataUpdateCoordinator(HoymilesDataUpdateCoordinator):
    """Keep live readings through brief outages, then report unavailability."""

    _last_successful_fetch: float | None = None
    _encryption_resync_callback: Callable[[], Awaitable[bool]] | None = None
    data_is_stale = False

    def set_encryption_resync_callback(
        self, resync_callback: Callable[[], Awaitable[bool]]
    ) -> None:
        """Register an async app-info callback that reports whether the key changed."""
        self._encryption_resync_callback = resync_callback

    async def _async_update_data(self):
        """Apply one grace period, measured from the last successful fetch."""
        if self._is_cloud_pause_active():
            self.data_is_stale = True
            if self._can_reuse_last_response():
                _LOGGER.debug(
                    "Skipping polling of DTU %s during the cloud upload pause",
                    self._config_entry.data.get(CONF_HOST),
                )
                return self.data
            raise UpdateFailed("No recent DTU data during the cloud upload pause")

        response = await self._async_try_fetch_data()

        if (
            response is None
            and await self._async_check_and_resync_encryption()
            and not self._is_cloud_pause_active()
        ):
            response = await self._async_try_fetch_data()

        if response is not None:
            self._last_successful_fetch = monotonic()
            self.data_is_stale = False
            return response

        self.data_is_stale = True
        if self._can_reuse_last_response():
            _LOGGER.debug(
                "DTU %s did not respond; reusing live data within the %s-second grace period",
                self._config_entry.data.get(CONF_HOST),
                LIVE_DATA_GRACE_SECONDS,
            )
            return self.data
        raise UpdateFailed("Unable to retrieve live data from DTU")

    async def _async_try_fetch_data(self):
        """Fetch a response, treating communication errors as no response."""
        try:
            return await self._async_fetch_data()
        except (OSError, TimeoutError) as err:
            _LOGGER.debug("Live data request failed: %s", err)
            return None

    async def _async_check_and_resync_encryption(self) -> bool:
        """Refresh the encryption key when the DTU answers but cannot be decoded.

        Encrypted DTUs generate a new key (enc_rand) whenever they restart, for
        example every morning or when PV power drops. Requests encrypted with
        the previous key are answered but cannot be parsed, which the library
        reports as NetworkState.Unknown (an unreachable DTU is Offline).
        """
        if (
            self._encryption_resync_callback is None
            or not getattr(self._dtu, "is_encrypted", False)
            or self._dtu.get_state() != NetworkState.Unknown
        ):
            return False
        return await self._encryption_resync_callback()

    def _is_cloud_pause_active(self) -> bool:
        """Reserve a quiet window beginning ten seconds before each five-minute mark."""
        duration = self._config_entry.data.get(
            CONF_CLOUD_PAUSE, DEFAULT_CLOUD_PAUSE_SECONDS
        )
        return duration > 0 and (dt_util.utcnow().timestamp() + 10) % 300 < duration

    def _can_reuse_last_response(self) -> bool:
        """Check whether cached data is still within the outage grace period."""
        return (
            self.data is not None
            and self._last_successful_fetch is not None
            and monotonic() - self._last_successful_fetch < LIVE_DATA_GRACE_SECONDS
        )

    async def _async_fetch_data(self):
        """Fetch a response, returning None when communication fails."""
        raise NotImplementedError


class PowerLimitUnit(Enum):
    """Units carried by the DTU's shared live power-limit field."""

    UNKNOWN = "unknown"
    PERCENT = "percent"
    WATTS = "watts"


class HoymilesRealDataUpdateCoordinator(HoymilesLiveDataUpdateCoordinator):
    """Resolve live readings and power-limit command confirmation."""

    def __init__(self, hass, dtu, config_entry, update_interval):
        """Only infer percent units for DTUs without temporary watt controls."""
        super().__init__(hass, dtu, config_entry, update_interval)
        self.power_limit_echo_unit = PowerLimitUnit.UNKNOWN
        self._power_limit_target: float | None = None
        self._power_limit_echo_confirmed = False
        self._pending_persistent_limit: float | None = None
        self._zero_percent_expected = False
        self.persistent_power_limit: float | None = None
        self.temporary_power_limit: float | None = None
        serial = config_entry.data.get(CONF_DTU_SERIAL_NUMBER)
        try:
            if get_dtu_model_type(bytes.fromhex(serial)) != DTUType.DTUBI:
                self.power_limit_echo_unit = PowerLimitUnit.PERCENT
        except (TypeError, ValueError):
            pass

    @property
    def temporary_power_limit_confirmed(self) -> bool:
        """Whether a fresh watt echo has confirmed the temporary target."""
        return (
            self.power_limit_echo_unit == PowerLimitUnit.WATTS
            and self._power_limit_echo_confirmed
        )

    def set_temporary_power_limit_target(self, value: float) -> None:
        """Establish watt units and wait for a matching live-data echo."""
        self._set_power_limit_target(value, PowerLimitUnit.WATTS)

    def set_persistent_power_limit_target(self, value: float) -> None:
        """Establish percent units and wait for fresh readback confirmation."""
        self._set_power_limit_target(value, PowerLimitUnit.PERCENT)

    def _set_power_limit_target(self, value: float, unit: PowerLimitUnit) -> None:
        """Replace the active command target and discard readings in the previous units."""
        self.power_limit_echo_unit = unit
        self._power_limit_target = value
        self._power_limit_echo_confirmed = False
        if unit == PowerLimitUnit.PERCENT:
            self._pending_persistent_limit = value
        self._zero_percent_expected = unit == PowerLimitUnit.PERCENT and value == 0
        self.persistent_power_limit = None
        self.temporary_power_limit = value if unit == PowerLimitUnit.WATTS else None
        self.async_update_listeners()

    def resolve_persistent_power_limit(
        self, config_coordinator: HoymilesLiveDataUpdateCoordinator
    ) -> tuple[float | None, bool]:
        """Return the percentage and assumed flag, confirming targets from either source."""
        value, source = self._resolve_persistent_readback(config_coordinator)
        if self._pending_persistent_limit is not None:
            if (
                value == self._pending_persistent_limit
                and source is not None
                and not source.data_is_stale
            ):
                self._pending_persistent_limit = None
            else:
                return self._pending_persistent_limit, True
        return value, source is not None and source.data_is_stale

    def _resolve_persistent_readback(
        self, config_coordinator: HoymilesLiveDataUpdateCoordinator
    ):
        """Prefer known live percentages over usable configuration fallback data."""
        if (
            self.last_update_success
            and self.data is not None
            and self.persistent_power_limit is not None
        ):
            return self.persistent_power_limit, self
        if (
            config_coordinator.last_update_success
            and config_coordinator.data is not None
        ):
            raw = getattr(config_coordinator.data, "limit_power_mypower", None)
            if raw is not None:
                value = raw / 10
                if math.isfinite(value) and 0 <= value <= MAX_POWER_LIMIT:
                    return value, config_coordinator
        return None, None

    def _read_configured_power_limits(self, response) -> list[tuple[str, int]]:
        """Extract raw limits for configured single-phase inverters once per response."""
        inverters = set(self._config_entry.data.get(CONF_INVERTERS, []))
        readings = []
        for inverter in getattr(response, "sgs_data", ()):
            serial = generate_inverter_serial_number(inverter.serial_number)
            if serial in inverters:
                readings.append((serial, inverter.power_limit))
        return readings

    def _update_persistent_power_limit_readback(self, readings) -> None:
        """Resolve a common percentage only for all configured single-phase inverters."""
        self.persistent_power_limit = None
        if (
            self.power_limit_echo_unit != PowerLimitUnit.PERCENT
            or self._config_entry.data.get(CONF_THREE_PHASE_INVERTERS)
        ):
            return
        inverters = set(self._config_entry.data.get(CONF_INVERTERS, []))
        limits = dict(readings)
        if (
            not inverters
            or limits.keys() != inverters
            or len(set(limits.values())) != 1
        ):
            return
        raw = next(iter(limits.values()))
        if not 0 <= raw <= MAX_POWER_LIMIT * 10:
            return
        value = raw / 10
        if (
            self._power_limit_target is not None
            and not self._power_limit_echo_confirmed
        ):
            if value != self._power_limit_target:
                return
        elif raw == 0 and not self._zero_percent_expected:
            return
        self._power_limit_echo_confirmed = True
        self._zero_percent_expected = raw == 0
        self.persistent_power_limit = value

    def _update_temporary_power_limit_readback(self, readings) -> None:
        """Read a known watt echo for the configured inverter."""
        if self.power_limit_echo_unit != PowerLimitUnit.WATTS:
            return
        values = [raw / 10 for _, raw in readings]
        if (
            len(values) != 1
            or not MIN_TEMPORARY_POWER_LIMIT_WATTS
            <= values[0]
            <= MAX_TEMPORARY_POWER_LIMIT_WATTS
        ):
            self.temporary_power_limit = None
            self._power_limit_echo_confirmed = False
            return
        value = values[0]
        if not self._power_limit_echo_confirmed and value != self._power_limit_target:
            _LOGGER.debug(
                "Waiting for temporary power limit echo: received %s W, expected %s W",
                value,
                self._power_limit_target,
            )
            return
        self.temporary_power_limit = value
        self._power_limit_echo_confirmed = True

    async def _async_fetch_data(self):
        """Update data via library."""
        _LOGGER.debug("Hoymiles data coordinator update")

        response = await self._dtu.async_get_real_data_new()

        if not response:
            _LOGGER.debug(
                "Unable to retrieve real data new. Inverter might be offline."
            )
        else:
            readings = self._read_configured_power_limits(response)
            self._update_persistent_power_limit_readback(readings)
            self._update_temporary_power_limit_readback(readings)
        return response


class HoymilesConfigUpdateCoordinator(HoymilesLiveDataUpdateCoordinator):
    """Config coordinator for Hoymiles integration."""

    async def _async_fetch_data(self):
        """Update data via library."""
        _LOGGER.debug("Hoymiles data coordinator update")

        response = await self._dtu.async_get_config()

        if not response:
            _LOGGER.debug("Unable to retrieve config data. Inverter might be offline.")

        return response


class HoymilesAppInfoUpdateCoordinator(HoymilesLiveDataUpdateCoordinator):
    """App Info coordinator for Hoymiles integration."""

    _last_encryption_resync: float | None = None

    async def async_resync_encryption(self) -> bool:
        """Refresh app info on demand and report whether the key changed."""
        now = monotonic()
        if (
            self._last_encryption_resync is not None
            and now - self._last_encryption_resync
            < ENC_RAND_RESYNC_MIN_INTERVAL_SECONDS
        ):
            return False
        self._last_encryption_resync = now

        previous_enc_rand = self._dtu.enc_rand
        await self.async_refresh()
        if self._dtu.enc_rand == previous_enc_rand:
            return False

        _LOGGER.info(
            "DTU %s uses a new encryption key; communication resynchronized",
            self._config_entry.data.get(CONF_HOST),
        )
        return True

    async def _async_fetch_data(self):
        """Update data via library."""
        _LOGGER.debug("Hoymiles data coordinator update")

        response = await self._dtu.async_app_information_data()

        if (
            response
            and response.dtu_info.dfs
            and is_encrypted_dtu(response.dtu_info.dfs)
        ):
            await async_check_and_update_enc_rand(
                self._hass,
                self._config_entry,
                self._dtu,
                response.dtu_info.enc_rand.hex(),
            )

        if not response:
            _LOGGER.debug(
                "Unable to retrieve app information data. Inverter might be offline."
            )
        return response


class HoymilesGatewayInfoUpdateCoordinator(HoymilesDataUpdateCoordinator):
    """Gateway Info coordinator for Hoymiles integration."""

    async def _async_update_data(self):
        """Update data via library."""
        _LOGGER.debug("Hoymiles gateway info coordinator update")

        response = await self._dtu.async_get_gateway_info()

        if not response:
            _LOGGER.debug("Unable to retrieve gateway info. Inverter might be offline.")
        return response


class HoymilesGatewayNetworkInfoUpdateCoordinator(HoymilesDataUpdateCoordinator):
    """Gateway Network Info coordinator for Hoymiles integration."""

    async def _async_update_data(self):
        """Update data via library."""
        _LOGGER.debug("Hoymiles network info coordinator update")

        response = await self._dtu.async_get_gateway_network_info(
            dtu_serial_number=int(self._dtu_serial_number)
        )

        if not response:
            _LOGGER.debug(
                "Unable to retrieve network information. Inverter might be offline."
            )
        return response


class HoymilesEnergyStorageUpdateCoordinator(HoymilesLiveDataUpdateCoordinator):
    """Energy Storage Update coordinator for Hoymiles integration."""

    def __init__(
        self,
        hass: homeassistant,
        dtu: DTU,
        config_entry: ConfigEntry,
        update_interval: timedelta,
        dtu_serial_number: int,
        inverters: list[int],
    ) -> None:
        """Initialize energy storage polling for the configured inverters."""
        self._dtu_serial_number = dtu_serial_number
        self._inverters = inverters
        super().__init__(hass, dtu, config_entry, update_interval)

    async def _async_fetch_data(self):
        """Update data via library."""
        _LOGGER.debug("Hoymiles energy storage coordinator update")

        responses = []

        for inverter in self._inverters:
            storage_data = await self._dtu.async_get_energy_storage_data(
                dtu_serial_number=int(self._dtu_serial_number),
                inverter_serial_number=inverter["inverter_serial_number"],
            )
            if storage_data is None:
                _LOGGER.debug(
                    "No response from inverter %s; retaining its position with missing data",
                    inverter["inverter_serial_number"],
                )
            responses.append(storage_data)

        if not any(response is not None for response in responses):
            _LOGGER.debug(
                "Unable to retrieve energy storage data. Inverter might be offline."
            )
            return None
        return responses
