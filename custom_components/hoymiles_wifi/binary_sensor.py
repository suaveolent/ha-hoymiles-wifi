"""Contains binary sensor entities for Hoymiles WiFi integration."""
from dataclasses import dataclass
import logging

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import callback
from hoymiles_wifi.inverter import NetworkState

from .const import DOMAIN, HASS_DATA_COORDINATOR
from .entity import HoymilesCoordinatorEntity

_LOGGER = logging.getLogger(__name__)

@dataclass(frozen=True)
class HoymilesBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Describes Homiles binary sensor entity."""

BINARY_SENSORS = (
    HoymilesBinarySensorEntityDescription(
        key="inverter",
        translation_key="inverter",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)

async def async_setup_entry(hass, entry, async_add_devices):
    """Set up sensor platform."""
    hass_data = hass.data[DOMAIN][entry.entry_id]
    data_coordinator = hass_data[HASS_DATA_COORDINATOR]
    sensors = []

    for description in BINARY_SENSORS:
        sensors.append(HoymilesInverterSensorEntity(data_coordinator, entry, description))

    async_add_devices(sensors)


class HoymilesInverterSensorEntity(HoymilesCoordinatorEntity, BinarySensorEntity):
    """Represents a binary sensor entity for Hoymiles WiFi integration."""

    def __init__(self, coordinator, config_entry, description):
        """Initialize the HoymilesInverterSensorEntity."""
        super().__init__(coordinator, config_entry, description)
        self._inverter = coordinator.get_inverter()
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
        """Update the state value of the binary sensor based on the inverter's network state."""
        inverter_state = self._inverter.get_state()
        if inverter_state == NetworkState.Online:
            self._native_value = True
        elif inverter_state == NetworkState.Offline:
            self._native_value = False
        else:
            self._native_value = None



