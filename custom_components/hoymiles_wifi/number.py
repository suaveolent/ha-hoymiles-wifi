"""Support for Hoymiles number sensors."""
import dataclasses
from dataclasses import dataclass
from enum import Enum
import logging

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_DTU_SERIAL_NUMBER,
    CONF_INVERTERS,
    DOMAIN,
    HASS_CONFIG_COORDINATOR,
)
from .entity import HoymilesCoordinatorEntity, HoymilesEntityDescription


class SetAction(Enum):
    """Enum for set actions."""

    POWER_LIMIT = 1


@dataclass(frozen=True)
class HoymilesNumberSensorEntityDescriptionMixin:
    """Mixin for required keys."""


@dataclass(frozen=True)
class HoymilesNumberSensorEntityDescription(
    HoymilesEntityDescription, NumberEntityDescription
):
    """Describes Hoymiles number sensor entity."""

    set_action: SetAction = None
    conversion_factor: float = None
    serial_number: str = None
    is_dtu_sensor: bool = False


CONFIG_CONTROL_ENTITIES = (
    HoymilesNumberSensorEntityDescription(
        key="limit_power_mypower",
        translation_key="limit_power_mypower",
        mode=NumberMode.SLIDER,
        device_class=NumberDeviceClass.POWER_FACTOR,
        set_action=SetAction.POWER_LIMIT,
        conversion_factor=0.1,
    ),
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Hoymiles number entities."""
    hass_data = hass.data[DOMAIN][config_entry.entry_id]
    config_coordinator = hass_data[HASS_CONFIG_COORDINATOR]
    dtu_serial_number = config_entry.data[CONF_DTU_SERIAL_NUMBER]
    inverters = config_entry.data[CONF_INVERTERS]

    sensors = []
    for description in CONFIG_CONTROL_ENTITIES:
        if description.is_dtu_sensor is True:
            updated_description = dataclasses.replace(
                description, serial_number=dtu_serial_number
            )
            sensors.append(
                HoymilesNumberEntity(
                    config_entry, updated_description, config_coordinator
                )
            )
        else:
            for inverter_serial in inverters:
                updated_description = dataclasses.replace(
                    description, serial_number=inverter_serial
                )
                sensors.append(
                    HoymilesNumberEntity(
                        config_entry, updated_description, config_coordinator
                    )
                )

    async_add_entities(sensors)


class HoymilesNumberEntity(HoymilesCoordinatorEntity, NumberEntity):
    """Hoymiles Number entity."""

    def __init__(
        self,
        config_entry: ConfigEntry,
        description: HoymilesNumberSensorEntityDescription,
        coordinator: HoymilesCoordinatorEntity,
    ) -> None:
        """Initialize the HoymilesNumberEntity."""
        super().__init__(config_entry, description, coordinator)
        self._attribute_name = description.key
        self._conversion_factor = description.conversion_factor
        self._set_action = description.set_action
        self._native_value = None
        self._assumed_state = False

        self.update_state_value()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.update_state_value()
        super()._handle_coordinator_update()

    @property
    def native_value(self) -> float:
        """Get the native value of the entity."""
        return self._native_value

    @property
    def assumed_state(self):
        """Return the assumed state of the entity."""
        return self._assumed_state

    async def async_set_native_value(self, value: float) -> None:
        """Set the native value of the entity.

        Args:
            value (float): The value to set.
        """
        if self._set_action == SetAction.POWER_LIMIT:
            dtu = self.coordinator.get_dtu()
            if value < 0 and value > 100:
                _LOGGER.error("Power limit value out of range")
                return
            await dtu.async_set_power_limit(value)
            await self.coordinator.async_request_refresh()
        else:
            _LOGGER.error("Invalid set action!")
            return

        self._assumed_state = True
        self._native_value = value

    def update_state_value(self):
        """Update the state value of the entity."""
        self._native_value = getattr(self.coordinator.data, self._attribute_name, None)

        self._assumed_state = False

        if self._native_value is not None and self._conversion_factor is not None:
            self._native_value *= self._conversion_factor
