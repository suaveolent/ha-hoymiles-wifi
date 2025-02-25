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
        entry: ConfigEntry,
        update_interval: timedelta,
    ) -> None:
        """Initialize the HoymilesCoordinatorEntity."""
        self._dtu = dtu
        self._hass = hass
        self._entry = entry

        _LOGGER.debug(
            "Setup entry with update interval %s. IP: %s",
            update_interval,
            entry.data.get(CONF_HOST),
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
