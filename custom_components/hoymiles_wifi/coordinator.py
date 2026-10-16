"""Coordinator for Hoymiles integration."""

from collections.abc import Awaitable, Callable
from datetime import timedelta
import logging
from time import monotonic

import homeassistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, Platform
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util
from hoymiles_wifi.const import (
    MAX_TEMPORARY_POWER_LIMIT_WATTS,
    MIN_TEMPORARY_POWER_LIMIT_WATTS,
)
from hoymiles_wifi.dtu import DTU, NetworkState
from hoymiles_wifi.hoymiles import generate_inverter_serial_number

from .const import (
    CONF_CLOUD_PAUSE,
    CONF_INVERTERS,
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
    _encryption_resync: Callable[[], Awaitable[bool]] | None = None
    data_is_stale = False

    def set_encryption_resync(self, resync: Callable[[], Awaitable[bool]]) -> None:
        """Register the callback that refreshes the DTU encryption key."""
        self._encryption_resync = resync

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

        if response is None and await self._async_resync_encryption():
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

    async def _async_resync_encryption(self) -> bool:
        """Refresh the encryption key when the DTU answers but cannot be decoded.

        Encrypted DTUs generate a new key (enc_rand) whenever they restart, for
        example every morning or when PV power drops. Requests encrypted with
        the previous key are answered but cannot be parsed, which the library
        reports as NetworkState.Unknown (an unreachable DTU is Offline).
        """
        if (
            self._encryption_resync is None
            or not getattr(self._dtu, "is_encrypted", False)
            or self._dtu.get_state() != NetworkState.Unknown
        ):
            return False
        return await self._encryption_resync()

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


class HoymilesRealDataUpdateCoordinator(HoymilesLiveDataUpdateCoordinator):
    """Data coordinator for Hoymiles integration."""

    temporary_power_limit: float | None = None
    temporary_power_limit_confirmed = False
    _temporary_power_limit_target: float | None = None

    def set_temporary_power_limit_target(self, value: float) -> None:
        """Establish watt units and wait for a matching live-data echo."""
        self._temporary_power_limit_target = value
        self.temporary_power_limit = value
        self.temporary_power_limit_confirmed = False
        self.async_update_listeners()

    def clear_temporary_power_limit(self) -> None:
        """Stop interpreting live echoes as watts after a persistent command."""
        self._temporary_power_limit_target = None
        self.temporary_power_limit = None
        self.temporary_power_limit_confirmed = False
        self.async_update_listeners()

    def _update_temporary_power_limit_readback(self, response) -> None:
        """Read a known watt echo for the configured inverter."""
        if self._temporary_power_limit_target is None:
            return

        inverters = self._config_entry.data.get(CONF_INVERTERS, [])
        readings = [
            inverter.power_limit / 10
            for inverter in response.sgs_data
            if generate_inverter_serial_number(inverter.serial_number) in inverters
        ]
        if (
            len(readings) != 1
            or not MIN_TEMPORARY_POWER_LIMIT_WATTS
            <= readings[0]
            <= MAX_TEMPORARY_POWER_LIMIT_WATTS
        ):
            self.temporary_power_limit = None
            self.temporary_power_limit_confirmed = False
            return

        value = readings[0]
        if (
            not self.temporary_power_limit_confirmed
            and value != self._temporary_power_limit_target
        ):
            _LOGGER.debug(
                "Waiting for temporary power limit echo: received %s W, expected %s W",
                value,
                self._temporary_power_limit_target,
            )
            return

        self.temporary_power_limit = value
        self.temporary_power_limit_confirmed = True

    async def _async_fetch_data(self):
        """Update data via library."""
        _LOGGER.debug("Hoymiles data coordinator update")

        response = await self._dtu.async_get_real_data_new()

        if not response:
            _LOGGER.debug(
                "Unable to retrieve real data new. Inverter might be offline."
            )
        else:
            self._update_temporary_power_limit_readback(response)
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
