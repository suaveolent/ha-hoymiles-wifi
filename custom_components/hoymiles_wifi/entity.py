"""Entity base for Hoymiles entities."""
from dataclasses import dataclass
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity, EntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from hoymiles_wifi.hoymiles import (
    generate_inverter_serial_number,
    get_dtu_model_name,
    get_inverter_model_name,
)

from .const import CONF_DTU_SERIAL_NUMBER, DOMAIN
from .coordinator import HoymilesDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class HoymilesEntityDescription(EntityDescription):
    """Class to describe a Hoymiles Button entity."""

    is_dtu_sensor: bool = False
    serial_number: str = None
    port_number: int = None


class HoymilesEntity(Entity):
    """Base class for Hoymiles entities."""

    _attr_has_entity_name = True

    def __init__(self, config_entry: ConfigEntry, description: EntityDescription):
        """Initialize the Hoymiles entity."""
        super().__init__()
        self.entity_description = description
        self._config_entry = config_entry
        self._attr_unique_id = f"hoymiles_{config_entry.entry_id}_{description.key}"
        self._attr_translation_placeholders = {
            "port_number": f"{description.port_number}"
        }

        dtu_serial_number = config_entry.data[CONF_DTU_SERIAL_NUMBER]

        if self.entity_description.is_dtu_sensor is True:
            device_translation_key = "dtu"
            device_model = get_dtu_model_name(self.entity_description.serial_number)
        else:
            device_model = get_inverter_model_name(
                self.entity_description.serial_number
            )
            device_translation_key = "inverter"

        device_info = DeviceInfo(
            identifiers={(DOMAIN, self.entity_description.serial_number)},
            translation_key=device_translation_key,
            manufacturer="Hoymiles",
            serial_number=self.entity_description.serial_number,
            model=device_model,
        )

        if self.entity_description.is_dtu_sensor is False:
            device_info["via_device"] = (DOMAIN, dtu_serial_number)

        self._attr_device_info = device_info


class HoymilesCoordinatorEntity(CoordinatorEntity, HoymilesEntity):
    """Represents a Hoymiles coordinator entity."""

    def __init__(
        self,
        config_entry: ConfigEntry,
        description: EntityDescription,
        coordinator: HoymilesDataUpdateCoordinator,
    ):
        """Pass coordinator to CoordinatorEntity."""
        CoordinatorEntity.__init__(self, coordinator)
        if self.coordinator is not None and hasattr(self.coordinator, "data"):
            self._dtu_serial_number = getattr(
                self.coordinator.data, "device_serial_number", ""
            )
            sgs_data = getattr(self.coordinator.data, "sgs_data", None)
            if sgs_data is not None:
                serial_number = getattr(sgs_data[0], "serial_number", None)
                if serial_number is not None:
                    self._inverter_serial_number = generate_inverter_serial_number(
                        serial_number
                    )

        HoymilesEntity.__init__(self, config_entry, description)
