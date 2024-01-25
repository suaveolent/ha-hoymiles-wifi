"""Entity base for Hoymiles entities."""
import logging

from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_SENSOR_PREFIX, DOMAIN

_LOGGER = logging.getLogger(__name__)


class HoymilesCoordinatorEntity(CoordinatorEntity):
    """Represents a Hoymiles coordinator entity."""

    _attr_has_entity_name = True

    def __init__(self, coordinator, config_entry):
        """Pass coordinator to CoordinatorEntity."""
        super().__init__(coordinator, config_entry)
        self._config_entry = config_entry

        self._sensor_prefix = f'{config_entry.data.get(CONF_SENSOR_PREFIX)} ' if config_entry.data.get(CONF_SENSOR_PREFIX) else ""

        self._dtu_sn = ""

        if self.coordinator is not None and hasattr(self.coordinator, "data"):
            self._dtu_sn = getattr(self.coordinator.data, "device_serial_number", "")

    @property
    def device_info(self):
        """Return device information about the sensor."""
        return {
            "identifiers": {(DOMAIN, self._config_entry.entry_id)},
            "name": "Hoymiles HMS-XXXXW-T2",
            "manufacturer": "Hoymiles",
            "model": "HMS-XXXXW-T2",
            "serial_number": self._dtu_sn,
            "via_device": (DOMAIN, "inverter_state"),
        }

