"""Contains binary sensor entities for Hoymiles WiFi integration."""

import dataclasses
from dataclasses import dataclass
import logging

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from hoymiles_wifi.dtu import NetworkState

from .const import (
    CONF_DTU_SERIAL_NUMBER,
    DOMAIN,
    HASS_DATA_COORDINATOR,
    HASS_ENERGY_STORAGE_DATA_COORDINATOR,
)
from .entity import HoymilesCoordinatorEntity, HoymilesEntityDescription

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class HoymilesBinarySensorEntityDescription(
    HoymilesEntityDescription, BinarySensorEntityDescription
):
    """Describes Homiles binary sensor entity."""


BINARY_SENSORS = (
    HoymilesBinarySensorEntityDescription(
        key="DTU",
        translation_key="dtu",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        is_dtu_sensor=True,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensor platform."""
    hass_data = hass.data[DOMAIN][config_entry.entry_id]
    coordinator = hass_data.get(HASS_DATA_COORDINATOR, None)
    if coordinator is None:
        coordinator = hass_data.get(HASS_ENERGY_STORAGE_DATA_COORDINATOR, None)

    dtu_serial_number = config_entry.data[CONF_DTU_SERIAL_NUMBER]

    hass_data = hass.data[DOMAIN][config_entry.entry_id]

    sensors = []

    for description in BINARY_SENSORS:
        updated_description = dataclasses.replace(
            description, serial_number=dtu_serial_number
        )
        sensors.append(
            HoymilesInverterSensorEntity(config_entry, updated_description, coordinator)
        )

    async_add_entities(sensors)


class HoymilesInverterSensorEntity(HoymilesCoordinatorEntity, BinarySensorEntity):
    """Represents a binary sensor entity for Hoymiles WiFi integration."""

    def __init__(
        self,
        config_entry: ConfigEntry,
        description: HoymilesBinarySensorEntityDescription,
        coordinator: HoymilesCoordinatorEntity,
    ):
        """Initialize the HoymilesInverterSensorEntity."""
        super().__init__(config_entry, description, coordinator)
        self._dtu = coordinator.get_dtu()
        self._native_value = None

        self.update_state_value()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.update_state_value()
        super()._handle_coordinator_update()

    @property
    def is_on(self):
        """Return the state of the binary sensor."""
        return self._native_value

    def update_state_value(self):
        """Update the state value of the binary sensor based on the DTU's network state."""
        dtu_state = self._dtu.get_state()
        if dtu_state == NetworkState.Online:
            self._native_value = True
        elif dtu_state == NetworkState.Offline:
            self._native_value = False
        else:
            self._native_value = None
