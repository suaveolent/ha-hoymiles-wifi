import logging

from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorEntityDescription,
    BinarySensorDeviceClass,
)

from .entity import HoymilesCoordinatorEntity

from hoymiles_wifi.inverter import (
    NetworkState
)

from homeassistant.core import callback

from homeassistant.const import (
    EntityCategory,
)

from .const import (
    DOMAIN,
    HASS_DATA_COORDINATOR,
)

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
    """Setup sensor platform."""
    hass_data = hass.data[DOMAIN][entry.entry_id]
    data_coordinator = hass_data[HASS_DATA_COORDINATOR]
    sensors = []

    # Inverter State
    for description in BINARY_SENSORS:
        sensors.append(HoymilesInverterSensorEntity(data_coordinator, entry, description))

    async_add_devices(sensors)



def get_hoymiles_unique_id(config_entry_id: str, key: str) -> str:
    """Create a _unique_id id for a Hoymiles entity"""
    return f"hoymiles_{config_entry_id}_{key}"


class HoymilesInverterSensorEntity(HoymilesCoordinatorEntity, BinarySensorEntity):

    def __init__(self, coordinator, config_entry, description):

        super().__init__(coordinator, config_entry)
        self.entity_description = description
        self._attr_unique_id = get_hoymiles_unique_id(config_entry.entry_id, description.key)
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
        return self._native_value
    
    
    def update_state_value(self):
        inverter_state = self._inverter.get_state()
        if inverter_state == NetworkState.Online:
            self._native_value = True
        elif inverter_state == NetworkState.Offline:
            self._native_value = False
        else:
            self._native_value = None



