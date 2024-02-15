"""Entity base for Hoymiles entities."""
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity, EntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity
import hoymiles_wifi.utils

from .const import CONF_SENSOR_PREFIX, DOMAIN
from .coordinator import HoymilesDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


class HoymilesEntity(Entity):
    """Base class for Hoymiles entities."""

    _attr_has_entity_name = True
    _inverter_serial_number = ""
    _dtu_serial_number = ""

    def __init__(self, config_entry: ConfigEntry, description: EntityDescription):
        """Initialize the Hoymiles entity."""
        super().__init__()
        self.entity_description = description
        self._config_entry = config_entry
        self._sensor_prefix = f' {config_entry.data.get(CONF_SENSOR_PREFIX)} ' if config_entry.data.get(CONF_SENSOR_PREFIX) else ""
        self._attr_unique_id = f"hoymiles_{config_entry.entry_id}_{description.key}"

        serial_number = ""
        device_name = "Hoymiles HMS-XXXXW-T2"
        device_model="HMS-XXXXW-T2"
        device_name_suffix = ""


        if hasattr(self.entity_description, "is_dtu_sensor") and self.entity_description.is_dtu_sensor is True:
            serial_number = self._dtu_serial_number
            device_name_suffix = " DTU"
        else:
            serial_number = self._inverter_serial_number

        device_name += self._sensor_prefix

        device_info = DeviceInfo(
            identifiers={(DOMAIN, self._config_entry.entry_id + device_name_suffix)},
            name = device_name + device_name_suffix,
            manufacturer="Hoymiles",
            serial_number= serial_number,
            model = device_model,
        )

        if not hasattr(self.entity_description, "is_dtu_sensor") or self.entity_description.is_dtu_sensor is False:
            device_info["via_device"] = (DOMAIN, self._config_entry.entry_id + " DTU")

        self._attr_device_info = device_info

class HoymilesCoordinatorEntity(CoordinatorEntity, HoymilesEntity):
    """Represents a Hoymiles coordinator entity."""

    def __init__(self, config_entry: ConfigEntry, description: EntityDescription, coordinator: HoymilesDataUpdateCoordinator):
        """Pass coordinator to CoordinatorEntity."""
        CoordinatorEntity.__init__(self, coordinator)
        if self.coordinator is not None and hasattr(self.coordinator, "data"):
            self._dtu_serial_number = getattr(self.coordinator.data, "device_serial_number", "")
            sgs_data = getattr(self.coordinator.data, "sgs_data", None)
            if(sgs_data is not None):
                serial_number = getattr(sgs_data[0], "serial_number", None)
                if(serial_number is not None):
                    self._inverter_serial_number = hoymiles_wifi.utils.generate_inverter_serial_number(serial_number)

        HoymilesEntity.__init__(self, config_entry, description)



