"""Coordinator for Hoymiles integration."""

from datetime import timedelta
import logging
import time

import homeassistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, Platform
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from hoymiles_wifi.dtu import DTU, NetworkState
from .util import async_sync_encryption_state


from .const import DOMAIN, ENCRYPTION_RESYNC_MIN_INTERVAL_SECONDS

_LOGGER = logging.getLogger(__name__)

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


class HoymilesRealDataUpdateCoordinator(HoymilesDataUpdateCoordinator):
    """Data coordinator for Hoymiles integration."""

    _last_encryption_resync: float | None = None

    async def _async_update_data(self):
        """Update data via library."""
        _LOGGER.debug("Hoymiles data coordinator update")

        response = await self._dtu.async_get_real_data_new()

        if not response and self._dtu.get_state() is NetworkState.Unknown:
            # Unknown is the state the library sets when a response arrived but
            # could not be parsed, which is exactly what a wrong encryption
            # state looks like. An unreachable DTU is Offline, and a DTU that
            # answered with an empty payload stays Online, so neither drags us
            # in here. App info is never encrypted, so it can always report the
            # current state. Re-sync and retry once before giving up.
            if await self._async_resync_encryption_state():
                response = await self._dtu.async_get_real_data_new()

        if not response:
            _LOGGER.debug(
                "Unable to retrieve real data new. Inverter might be offline."
            )
        return response

    async def _async_resync_encryption_state(self) -> bool:
        """Re-read the DTU's encryption state. Returns True if it changed."""
        now = time.monotonic()
        if (
            self._last_encryption_resync is not None
            and now - self._last_encryption_resync
            < ENCRYPTION_RESYNC_MIN_INTERVAL_SECONDS
        ):
            # A payload can be unparseable for reasons that re-reading the
            # encryption state will never fix. Probing on every poll would add a
            # request per cycle indefinitely, and the library serialises requests
            # behind a mutex with a 2s floor between them.
            _LOGGER.debug("Encryption re-sync throttled, skipping")
            return False

        self._last_encryption_resync = now

        was_encrypted = self._dtu.is_encrypted
        previous_enc_rand = self._dtu.enc_rand

        app_info = await self._dtu.async_app_information_data()
        if not app_info:
            return False

        async_sync_encryption_state(
            self._hass, self._config_entry, self._dtu, app_info.dtu_info
        )

        changed = (
            was_encrypted != self._dtu.is_encrypted
            or previous_enc_rand != self._dtu.enc_rand
        )
        if changed:
            _LOGGER.info(
                "DTU encryption state changed (encrypted=%s), retrying real data",
                self._dtu.is_encrypted,
            )
        return changed


class HoymilesConfigUpdateCoordinator(HoymilesDataUpdateCoordinator):
    """Config coordinator for Hoymiles integration."""

    async def _async_update_data(self):
        """Update data via library."""
        _LOGGER.debug("Hoymiles data coordinator update")

        response = await self._dtu.async_get_config()

        if not response:
            _LOGGER.debug("Unable to retrieve config data. Inverter might be offline.")

        return response


class HoymilesAppInfoUpdateCoordinator(HoymilesDataUpdateCoordinator):
    """App Info coordinator for Hoymiles integration."""

    async def _async_update_data(self):
        """Update data via library."""
        _LOGGER.debug("Hoymiles data coordinator update")

        response = await self._dtu.async_app_information_data()

        if response:
            # App info is never encrypted, so this is the one call that still
            # works after the DTU switches encryption on, and therefore the
            # place where we detect and persist that switch.
            #
            # Deliberately not gated on `dtu_info.dfs` being non-zero: a DTU
            # that reports dfs == 0 is announcing "no flags set", which includes
            # encryption being off, and that has to be able to turn a stale
            # encrypted state back off.
            async_sync_encryption_state(
                self._hass,
                self._config_entry,
                self._dtu,
                response.dtu_info,
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


class HoymilesEnergyStorageUpdateCoordinator(HoymilesDataUpdateCoordinator):
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
        self._dtu_serial_number = dtu_serial_number
        self._inverters = inverters
        super().__init__(hass, dtu, config_entry, update_interval)

    async def _async_update_data(self):
        """Update data via library."""
        _LOGGER.debug("Hoymiles energy storage coordinator update")

        responses = []

        for inverter in self._inverters:
            storage_data = await self._dtu.async_get_energy_storage_data(
                dtu_serial_number=int(self._dtu_serial_number),
                inverter_serial_number=inverter["inverter_serial_number"],
            )
            if storage_data is not None:
                responses.append(storage_data)

        if not responses:
            _LOGGER.debug(
                "Unable to retrieve energy storage data. Inverter might be offline."
            )
        return responses
