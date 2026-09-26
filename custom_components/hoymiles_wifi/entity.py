"""Entity base for Hoymiles entities."""

from dataclasses import dataclass
import logging

from enum import Enum

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity, EntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from hoymiles_wifi.hoymiles import (
    DTUType,
    get_dtu_model_name,
    get_inverter_model_name,
    get_meter_model_name,
)

from .const import CONF_DTU_SERIAL_NUMBER, DOMAIN
from .coordinator import (
    HoymilesDataUpdateCoordinator,
)

_LOGGER = logging.getLogger(__name__)


class DeviceType(Enum):
    """Device type."""

    ALL_DEVICES = 0
    SINGLE_PHASE_METER = 1
    THREE_PHASE_METER = 3


@dataclass(frozen=True)
class HoymilesEntityDescription(EntityDescription):
    """Class to describe a Hoymiles Button entity."""

    is_dtu_sensor: bool = False
    serial_number: str = None
    port_number: int = None
    supported_dtu_types: list[DTUType] = None
    phase: str = None


class HoymilesEntity(Entity):
    """Base class for Hoymiles entities."""

    _attr_has_entity_name = True

    def __init__(self, config_entry: ConfigEntry, description: EntityDescription):
        """Initialize the Hoymiles entity."""
        super().__init__()
        self.entity_description = description
        self._config_entry = config_entry
        self._attr_unique_id = f"hoymiles_{config_entry.entry_id}_{description.key}"

        if description.port_number:
            self._attr_translation_placeholders = {
                "port_number": f"{description.port_number}"
            }
        if description.phase:
            self._attr_translation_placeholders = {"phase": f"{description.phase}"}

        serial_number = str(self.entity_description.serial_number)

        if self.entity_description.is_dtu_sensor is True:
            device_translation_key = "dtu"
            device_model = get_dtu_model_name(self.entity_description.serial_number)
        else:
            if "meter" in self.entity_description.key:
                device_model = get_meter_model_name(
                    self.entity_description.serial_number
                )
                device_translation_key = "meter"
            else:
                if (
                    hasattr(self.entity_description, "model_name")
                    and self.entity_description.model_name
                ):
                    device_model = self.entity_description.model_name
                    device_translation_key = "hybrid_inverter"
                else:
                    device_model = get_inverter_model_name(
                        self.entity_description.serial_number
                    )
                    device_translation_key = "inverter"

        device_info = DeviceInfo(
            identifiers={(DOMAIN, serial_number)},
            translation_key=device_translation_key,
            manufacturer="Hoymiles",
            serial_number=serial_number.upper(),
            model=device_model,
        )

        self._attr_device_info = device_info

    @property
    def device_info(self) -> DeviceInfo:
        """Link connected devices to the DTU owned by this config entry."""
        device_info = self._attr_device_info.copy()
        if not self.entity_description.is_dtu_sensor:
            identifier = (
                DOMAIN, str(self._config_entry.data[CONF_DTU_SERIAL_NUMBER])
            )
            if hasattr(dr, "async_get_device_id_by_identifier"):
                device_info["via_device_id"] = dr.async_get_device_id_by_identifier(
                    self.hass, identifier, config_entry_id=self._config_entry.entry_id
                )
            else:
                # Compatibility with Home Assistant before the 2026.8 registry API.
                device_info["via_device"] = identifier
        return device_info


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
        HoymilesEntity.__init__(self, config_entry, description)
