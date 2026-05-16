"""Support for Hoymiles number sensors."""

import asyncio
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
    CONF_THREE_PHASE_INVERTERS,
    DOMAIN,
    HASS_CONFIG_COORDINATOR,
    HASS_DATA_COORDINATOR,
)
from .entity import HoymilesCoordinatorEntity, HoymilesEntityDescription

from hoymiles_wifi.hoymiles import DTUType, get_dtu_model_type


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
        is_dtu_sensor=True,
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
    config_coordinator = hass_data.get(HASS_CONFIG_COORDINATOR, None)
    data_coordinator = hass_data.get(HASS_DATA_COORDINATOR, None)
    single_phase_inverters = config_entry.data.get(CONF_INVERTERS, [])
    three_phase_inverters = config_entry.data.get(CONF_THREE_PHASE_INVERTERS, [])
    dtu_serial_number = config_entry.data[CONF_DTU_SERIAL_NUMBER]

    if single_phase_inverters or three_phase_inverters:
        sensors = []
        for description in CONFIG_CONTROL_ENTITIES:
            if description.is_dtu_sensor is True:
                updated_description = dataclasses.replace(
                    description, serial_number=dtu_serial_number
                )
                sensors.append(
                    HoymilesNumberEntity(
                        config_entry, updated_description, config_coordinator, data_coordinator
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
        data_coordinator: HoymilesCoordinatorEntity = None,
    ) -> None:
        """Initialize the HoymilesNumberEntity."""
        super().__init__(config_entry, description, coordinator)
        self._data_coordinator = data_coordinator
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


    async def async_added_to_hass(self) -> None:
        """Register updates from the data coordinator as well."""
        await super().async_added_to_hass()
        if self._data_coordinator is not None:
            self.async_on_remove(
                self._data_coordinator.async_add_listener(
                    self._handle_coordinator_update
                )
            )

        async def _delayed_config_refresh():
            await asyncio.sleep(15)  # Wait for integration and DTU to settle
            await self.coordinator.async_request_refresh()

        self.hass.async_create_task(_delayed_config_refresh())

    def update_state_value(self):
        """Update the state value of the entity."""

        # Try to get value from config coordinator
        self._native_value = getattr(
            self.coordinator.data,
            self._attribute_name,
            None,
        )

        # Fallback to data coordinator if config value is not available or defaults to 0
        if (self._native_value is None or self._native_value == 0) and self._data_coordinator is not None and self._data_coordinator.data is not None:
            if self._attribute_name == "limit_power_mypower":
                data = self._data_coordinator.data
                if hasattr(data, "sgs_data") and data.sgs_data and len(data.sgs_data) > 0:
                    self._native_value = getattr(data.sgs_data[0], "power_limit", None)
                elif hasattr(data, "tgs_data") and data.tgs_data and len(data.tgs_data) > 0:
                    self._native_value = getattr(data.tgs_data[0], "power_limit", None)

        self._assumed_state = False

        if self._native_value is not None and self._conversion_factor is not None:
            self._native_value *= self._conversion_factor
