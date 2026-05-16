"""Coordinator for Hoymiles integration."""

from datetime import timedelta
import logging

import homeassistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, Platform
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from hoymiles_wifi.dtu import DTU
from .util import is_encrypted_dtu, async_check_and_update_enc_rand
from hoymiles_wifi.protobuf import NetworkInfo_pb2, CommandPB_pb2


from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR, Platform.NUMBER, Platform.BINARY_SENSOR, Platform.BUTTON]

# --- RECONNECTION: Log a reminder every N consecutive failures to avoid log spam
# during extended outages (e.g., overnight). First failure always logs a warning.
_FAILURE_LOG_INTERVAL = 10


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

        # --- RECONNECTION: Track consecutive update failures for smart logging.
        # This counter increments on each failed update and resets on success.
        # It prevents log spam during multi-hour outages while still logging
        # periodic reminders so the user knows the DTU is still offline.
        self._consecutive_failures: int = 0

        _LOGGER.debug(
            "Setup entry with update interval %s. IP: %s",
            update_interval,
            config_entry.data.get(CONF_HOST),
        )

        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=update_interval)

    def get_dtu(self) -> DTU:
        """Get the DTU object."""
        return self._dtu

    def _handle_update_failure(self, coordinator_name: str) -> None:
        """Handle a failed DTU update with smart logging.

        --- RECONNECTION: This method is called when the DTU returns None
        (offline or unreachable). It raises UpdateFailed which tells HA's
        DataUpdateCoordinator that the update did NOT succeed. This causes:
        - All entities using this coordinator to be marked as "unavailable"
        - The coordinator to continue polling at its normal interval
        - Automatic recovery when the next update succeeds

        Logging strategy:
        - First failure: WARNING with the coordinator name
        - Every Nth failure: WARNING reminder with failure count
        - Other failures: DEBUG only (to avoid log spam)
        """
        self._consecutive_failures += 1

        if self._consecutive_failures == 1:
            _LOGGER.warning(
                "%s: DTU is offline or unreachable. Entities will be marked as "
                "unavailable. Will automatically recover when DTU comes back online.",
                coordinator_name,
            )
        elif self._consecutive_failures % _FAILURE_LOG_INTERVAL == 0:
            _LOGGER.warning(
                "%s: DTU still offline after %d consecutive failed updates. "
                "Will keep retrying automatically.",
                coordinator_name,
                self._consecutive_failures,
            )
        else:
            _LOGGER.debug(
                "%s: DTU still offline (failure #%d).",
                coordinator_name,
                self._consecutive_failures,
            )

        if self._consecutive_failures == 100:
            _LOGGER.warning(
                "%s: DTU has been offline for an extended period. Automatically reloading the integration to ensure a clean reconnect state when it wakes up.",
                coordinator_name,
            )
            self._hass.async_create_task(
                self._hass.config_entries.async_reload(self._config_entry.entry_id)
            )

        raise UpdateFailed(
            f"{coordinator_name}: Unable to retrieve data from DTU. "
            f"Inverter/DTU might be offline (failure #{self._consecutive_failures})."
        )

    def _handle_update_success(self, coordinator_name: str) -> None:
        """Handle a successful DTU update.

        --- RECONNECTION: Logs recovery info when the DTU comes back online
        after being offline. Resets the failure counter so entities will be
        marked as "available" again by HA's DataUpdateCoordinator.
        """
        if self._consecutive_failures > 0:
            _LOGGER.info(
                "%s: DTU is back online after %d consecutive failed updates. "
                "Resuming normal operation.",
                coordinator_name,
                self._consecutive_failures,
            )
        self._consecutive_failures = 0


class HoymilesRealDataUpdateCoordinator(HoymilesDataUpdateCoordinator):
    """Data coordinator for Hoymiles integration."""

    async def _async_update_data(self):
        """Update data via library.

        --- RECONNECTION: Raises UpdateFailed if DTU returns None, enabling
        HA's automatic retry and entity unavailability marking. When DTU is
        offline (e.g., overnight), entities become unavailable. When it comes
        back online, entities automatically recover without manual intervention.
        """
        _LOGGER.debug("Hoymiles real data coordinator update")

        try:
            response = await self._dtu.async_get_real_data_new()
        except Exception as err:
            # --- RECONNECTION: Catch any unexpected exceptions from the DTU library
            # (e.g., unhandled socket errors) and convert them to UpdateFailed
            # so the coordinator doesn't stop polling entirely.
            self._handle_update_failure("RealData")
            return  # pragma: no cover — _handle_update_failure always raises

        if not response:
            self._handle_update_failure("RealData")
            return  # pragma: no cover — _handle_update_failure always raises

        self._handle_update_success("RealData")
        return response


class HoymilesConfigUpdateCoordinator(HoymilesDataUpdateCoordinator):
    """Config coordinator for Hoymiles integration."""

    async def _async_update_data(self):
        """Update data via library.

        --- RECONNECTION: Same pattern as RealData — raises UpdateFailed on
        failure to enable automatic recovery.
        """
        _LOGGER.debug("Hoymiles config coordinator update")

        try:
            response = await self._dtu.async_get_config()
        except Exception as err:
            _LOGGER.debug("Config: Exception while querying data: %s", err)
            return None

        if not response:
            _LOGGER.debug("Unable to retrieve config data. Inverter might be offline.")
            return None

        self._handle_update_success("Config")
        return response


class HoymilesAppInfoUpdateCoordinator(HoymilesDataUpdateCoordinator):
    """App Info coordinator for Hoymiles integration."""

    async def _async_update_data(self):
        """Update data via library.

        --- RECONNECTION: Same pattern — raises UpdateFailed on failure.
        Encryption check is only performed on successful responses.
        """
        _LOGGER.debug("Hoymiles app info coordinator update")

        try:
            response = await self._dtu.async_app_information_data()
        except Exception as err:
            _LOGGER.debug("AppInfo: Exception while querying data: %s", err)
            return None

        if not response:
            _LOGGER.debug("Unable to retrieve app info data. Inverter might be offline.")
            return None

        # Encryption handling only runs on successful responses
        if response.dtu_info.dfs:
            if is_encrypted_dtu(response.dtu_info.dfs):
                await async_check_and_update_enc_rand(
                    self._hass,
                    self._config_entry,
                    self._dtu,
                    response.dtu_info.enc_rand.hex(),
                )

        self._handle_update_success("AppInfo")
        return response


class HoymilesGatewayInfoUpdateCoordinator(HoymilesDataUpdateCoordinator):
    """Gateway Info coordinator for Hoymiles integration."""

    async def _async_update_data(self):
        """Update data via library.

        --- RECONNECTION: Same pattern — raises UpdateFailed on failure.
        """
        _LOGGER.debug("Hoymiles gateway info coordinator update")

        try:
            response = await self._dtu.async_get_gateway_info()
        except Exception as err:
            self._handle_update_failure("GatewayInfo")
            return

        if not response:
            self._handle_update_failure("GatewayInfo")
            return

        self._handle_update_success("GatewayInfo")
        return response


class HoymilesGatewayNetworkInfoUpdateCoordinator(HoymilesDataUpdateCoordinator):
    """Gateway Network Info coordinator for Hoymiles integration."""

    async def _async_update_data(self):
        """Update data via library."""
        _LOGGER.debug("Hoymiles network info coordinator update")

        try:
            response = await self._dtu.async_get_gateway_network_info(
                dtu_serial_number=int(self._dtu_serial_number)
            )
        except Exception as err:
            self._handle_update_failure("NetworkInfo")
            return

        if not response:
            self._handle_update_failure("NetworkInfo")
            return

        self._handle_update_success("NetworkInfo")
        return response


class HoymilesNetworkInfoUpdateCoordinator(HoymilesDataUpdateCoordinator):
    """Network Info coordinator for DTU status."""

    async def _async_update_data(self):
        """Update data via library."""
        _LOGGER.debug("Hoymiles DTU network info coordinator update")

        try:
            # Command 1: network-info
            network_info = await self._dtu.async_network_info()
            # Command 2: gateway-network-info (yields IP, DHCP, etc.)
            gw_info = await self._dtu.async_get_gateway_network_info(
                dtu_serial_number=int(self._dtu._dtu_id)
            )
            
            # Combine into a single result object for the sensor
            return {
                "network_info": network_info,
                "gw_info": gw_info
            }
        except Exception as err:
            _LOGGER.debug("Error fetching network info: %s", err)
            self._handle_update_failure("DTUNetworkInfo")
            return

        if not network_info and not gw_info:
            self._handle_update_failure("DTUNetworkInfo")
            return

        self._handle_update_success("DTUNetworkInfo")
        return {"network_info": network_info, "gw_info": gw_info}


class HoymilesAlarmListUpdateCoordinator(HoymilesDataUpdateCoordinator):
    """Alarm List coordinator for DTU health."""

    async def _async_update_data(self):
        """Update data via library."""
        _LOGGER.debug("Hoymiles alarm list coordinator update")

        try:
            response = await self._dtu.async_get_alarm_list()
        except Exception as err:
            self._handle_update_failure("AlarmList")
            return

        if not response:
            self._handle_update_failure("AlarmList")
            return

        self._handle_update_success("AlarmList")
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
        """Update data via library.

        --- RECONNECTION: Same pattern — raises UpdateFailed if no data could
        be retrieved from any inverter, enabling automatic recovery.
        """
        _LOGGER.debug("Hoymiles energy storage coordinator update")

        responses = []

        for inverter in self._inverters:
            try:
                storage_data = await self._dtu.async_get_energy_storage_data(
                    dtu_serial_number=int(self._dtu_serial_number),
                    inverter_serial_number=inverter["inverter_serial_number"],
                )
            except Exception as err:
                _LOGGER.debug(
                    "EnergyStorage: Exception querying inverter %s: %s",
                    inverter.get("inverter_serial_number", "unknown"),
                    err,
                )
                continue

            if storage_data is not None:
                responses.append(storage_data)

        if not responses:
            self._handle_update_failure("EnergyStorage")
            return

        self._handle_update_success("EnergyStorage")
        return responses
