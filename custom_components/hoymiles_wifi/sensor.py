import logging

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
)
from homeassistant.core import callback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.const import POWER_WATT


from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, entry, async_add_devices):
    """Setup sensor platform."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    sensors = []

    data = {
        "attribute_name": "pv_current_power",
    }

    sensors.append(HoymilesDataSensorEntity(coordinator, entry, data))

    async_add_devices(sensors)

class HoymilesDataSensorEntity(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True
    """An entity using CoordinatorEntity.

    The CoordinatorEntity class provides:
      should_poll
      async_update
      async_added_to_hass
      available

    """

    def __init__(self, coordinator, config_entry, data):
        """Pass coordinator to CoordinatorEntity."""
        super().__init__(coordinator)
        self._config_entry = config_entry
        self._attribute_name = data["attribute_name"]
        self._state = 0.0
        self._uniqe_id = f"hoymiles_{self._attribute_name}"

        self.update_state_value()


    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
    
        #self._state = self.coordinator.data[self.idx]["state"]

        self.update_state_value()


        super()._handle_coordinator_update()

    @property
    def name(self):
        """Return the name of the sensor."""
        return "PV Current Power"
    
    @property
    def unique_id(self):
        """Return a unique ID to use for this entity."""
        return self._uniqe_id
    
    @property
    def state(self):
        """Return the state of the sensor."""
        return self._state

    @property
    def unit_of_measurement(self):
        """Return the unit of measurement."""
        return POWER_WATT

    @property
    def device_class(self):
        """Return the device class of the sensor."""
        return SensorDeviceClass.POWER
    

    def update_state_value(self):
        attribute_value = getattr(self.coordinator.data, self._attribute_name, None)
        self._state = attribute_value / 10.0
    

