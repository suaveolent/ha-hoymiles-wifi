import logging

from enum import Enum

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from homeassistant.core import callback

from homeassistant.components.number import (
    NumberEntity,
    NumberDeviceClass,
    NumberMode,
    NumberEntityDescription
)


from .entity import HoymilesCoordinatorEntity

from .const import (
    DOMAIN,
    HASS_CONFIG_COORDINATOR,
)

class SetAction(Enum):
    POWER_LIMIT = 1

CONFIG_CONTROL_ENTITIES = [
    {
        "name": "Power Limit",
        "attribute_name": "limit_power_mypower",
        "conversion_factor": 0.1,
        "mode": NumberMode.SLIDER,
        "device_class": NumberDeviceClass.POWER_FACTOR,
        "set_action": SetAction.POWER_LIMIT,
    },
]



_LOGGER = logging.getLogger(__name__)

def get_hoymiles_unique_id(config_entry_id: str, key: str) -> str:
    """Create a _unique_id id for a Hoymiles entity"""
    return f"hoymiles_{config_entry_id}_{key}"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
        hass_data = hass.data[DOMAIN][entry.entry_id]
        config_coordinator = hass_data[HASS_CONFIG_COORDINATOR] 
        async_add_entities(
            HoymilesNumberEntity(config_coordinator, entry, data) for data in CONFIG_CONTROL_ENTITIES
        )

class HoymilesNumberEntity(HoymilesCoordinatorEntity, NumberEntity):
    """Hoymiles Number entity."""

    def __init__(self, coordinator, config_entry: ConfigEntry, data) -> None:
        super().__init__(coordinator, config_entry)
        self._name = data["name"]
        self._attribute_name = data["attribute_name"]
        self._conversion_factor = data["conversion_factor"]
        self._mode = data["mode"]
        self._device_class = data["device_class"]
        self._set_action = data["set_action"]
        self._native_value = None
        self._assumed_state = False
        self._unique_id = get_hoymiles_unique_id(config_entry.entry_id, self._attribute_name)

        self.update_state_value()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.update_state_value()
        super()._handle_coordinator_update()

    @property
    def name(self):
        return self._name
    
    @property
    def unique_id(self):
        return self._unique_id

    @property
    def native_value(self) -> float:
        return self._native_value
        
    @property
    def mode(self):
        return self._mode
    
    @property
    def device_class(self):
        return self._device_class
    
    @property
    def assumed_state(self):
        return self._assumed_state

    def set_native_value(self, value: float) -> None:

        if self._set_action == SetAction.POWER_LIMIT:
                inverter = self.coordinator.get_inverter()
                if(value < 0 and value > 100):
                    _LOGGER.error("Power limit value out of range")
                    return
                inverter.set_power_limit(value)
        else:
            _LOGGER.error("Invalid set action!")
            return 
        
        self._assumed_state = True
        self._native_value = value


    def update_state_value(self):
        self._native_value =  getattr(self.coordinator.data, self._attribute_name, None)

        self._assumed_state = False

        if self._native_value != None and self._conversion_factor != None:
            self._native_value *= self._conversion_factor