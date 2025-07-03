"""Coordinator for Hoymiles integration."""

from datetime import timedelta
import logging

import homeassistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, Platform
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from hoymiles_wifi.dtu import DTU

from .const import DOMAIN

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

    async def _async_update_data(self):
        """Update data via library."""
        _LOGGER.debug("Hoymiles data coordinator update")

        response = await self._dtu.async_get_real_data_new()

        if not response:
            _LOGGER.debug(
                "Unable to retrieve real data new. Inverter might be offline."
            )
        return response


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

        if not response:
            _LOGGER.debug(
                "Unable to retrieve app information data. Inverter might be offline."
            )
        return response


class HoymilesGatewayInfoUpdateCoordinator(HoymilesDataUpdateCoordinator):
    """Gateway Info coordinator for Hoymiles integration."""

    async def _async_update_data(self):
        """Update data via library."""
        _LOGGER.debug("Hoymiles data coordinator update")

        response = await self._dtu.async_get_gateway_info()

        if not response:
            _LOGGER.debug(
                "Unable to retrieve app information data. Inverter might be offline."
            )
        return response


class HoymilesGatewayNetworkInfoUpdateCoordinator(HoymilesDataUpdateCoordinator):
    """Gateway Network Info coordinator for Hoymiles integration."""

    async def _async_update_data(self):
        """Update data via library."""
        _LOGGER.debug("Hoymiles data coordinator update")

        response = await self._dtu.async_get_energy_storage_registry(
            dtu_serial_number=self._dtu_serial_number,
        )

        if not response:
            _LOGGER.debug(
                "Unable to retrieve app information data. Inverter might be offline."
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
        inverter_serial_numbers: list[int],
    ) -> None:
        self._dtu_serial_number = dtu_serial_number
        self._inverter_serial_numbers = inverter_serial_numbers
        super().__init__(hass, dtu, config_entry, update_interval)

    async def _async_update_data(self):
        """Update data via library."""
        _LOGGER.debug("Hoymiles energy storage coordinator update")

        responses = []
        for inverter_serial_number in self._inverter_serial_numbers:
            storage_data = await self._dtu.async_get_energy_storage_data(
                dtu_serial_number=int(self._dtu_serial_number),
                inverter_serial_number=inverter_serial_number,
            )
            if storage_data is not None:
                responses.append(storage_data)

        response = await self._dtu.async_app_information_data()

        if not response:
            _LOGGER.debug(
                "Unable to retrieve app information data. Inverter might be offline."
            )
        return response
