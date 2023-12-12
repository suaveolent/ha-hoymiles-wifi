import logging

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    STATE_CLASS_MEASUREMENT,
    STATE_CLASS_TOTAL_INCREASING,
)
from homeassistant.core import callback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.const import (
    ELECTRIC_CURRENT_AMPERE,
    ELECTRIC_POTENTIAL_VOLT,
    ENERGY_WATT_HOUR,
    FREQUENCY_HERTZ,
    POWER_WATT,
    TEMP_CELSIUS,
)


from .const import (
    CONF_SENSOR_PREFIX,
    DOMAIN,
    HASS_DATA_COORDINATOR,
)

_LOGGER = logging.getLogger(__name__)


HOYMILES_SENSORS = [
    {
        "name": "PV Current Power",
        "attribute_name": "pv_current_power",
        "conversion_factor": 0.1,
        "unit_of_measurement": POWER_WATT,
        "device_class": SensorDeviceClass.POWER,
        "state_class": STATE_CLASS_MEASUREMENT,
    },
    {
        "name": "PV Daily Yield",
        "attribute_name": "pv_daily_yield",
        "conversion_factor": None,
        "unit_of_measurement": ENERGY_WATT_HOUR,
        "device_class": SensorDeviceClass.ENERGY,
        "state_class": STATE_CLASS_TOTAL_INCREASING,
    },
    {
        "name": "Inverter Grid Voltage",
        "attribute_name": "inverter_state[0].grid_voltage",
        "conversion_factor": 0.1,
        "unit_of_measurement": ELECTRIC_POTENTIAL_VOLT,
        "device_class": SensorDeviceClass.VOLTAGE,
        "state_class": STATE_CLASS_MEASUREMENT,
    },
    {
        "name": "Inverter Grid Frequency",
        "attribute_name": "inverter_state[0].grid_freq",
        "conversion_factor": 0.01,
        "unit_of_measurement": FREQUENCY_HERTZ,
        "device_class": SensorDeviceClass.FREQUENCY,
        "state_class": STATE_CLASS_MEASUREMENT,
    },
    {
        "name": "Inverter Temperature",
        "attribute_name": "inverter_state[0].temperature",
        "conversion_factor": 0.1,
        "unit_of_measurement": TEMP_CELSIUS,
        "device_class": SensorDeviceClass.TEMPERATURE,
        "state_class": STATE_CLASS_MEASUREMENT,
    },
    {
        "name": "Port 1 Voltage",
        "attribute_name": "port_state[0].pv_vol",
        "conversion_factor": 0.1,
        "unit_of_measurement": ELECTRIC_POTENTIAL_VOLT,
        "device_class": SensorDeviceClass.VOLTAGE,
        "state_class": STATE_CLASS_MEASUREMENT,
    },
    {
        "name": "Port 1 Current",
        "attribute_name": "port_state[0].pv_cur",
        "conversion_factor": 0.01,
        "unit_of_measurement": ELECTRIC_CURRENT_AMPERE,
        "device_class": SensorDeviceClass.CURRENT,
        "state_class": STATE_CLASS_MEASUREMENT,
    },
    {
        "name": "Port 1 Power",
        "attribute_name": "port_state[0].pv_power",
        "conversion_factor": 0.1,
        "unit_of_measurement": POWER_WATT,
        "device_class": SensorDeviceClass.POWER,
        "state_class": STATE_CLASS_MEASUREMENT,
    },
    {
        "name": "Port 1 Energy Total",
        "attribute_name": "port_state[0].pv_energy_total",
        "conversion_factor": None,
        "unit_of_measurement": ENERGY_WATT_HOUR,
        "device_class": SensorDeviceClass.ENERGY,
        "state_class": STATE_CLASS_TOTAL_INCREASING,
    },
    {
        "name": "Port 1 Daily Yield",
        "attribute_name": "port_state[0].pv_daily_yield",
        "conversion_factor": None,
        "unit_of_measurement": ENERGY_WATT_HOUR,
        "device_class": SensorDeviceClass.ENERGY,
        "state_class": STATE_CLASS_TOTAL_INCREASING,
    },
        {
        "name": "Port 2 Voltage",
        "attribute_name": "port_state[1].pv_vol",
        "conversion_factor": 0.1,
        "unit_of_measurement": ELECTRIC_POTENTIAL_VOLT,
        "device_class": SensorDeviceClass.VOLTAGE,
        "state_class": STATE_CLASS_MEASUREMENT,
    },
    {
        "name": "Port 2 Current",
        "attribute_name": "port_state[1].pv_cur",
        "conversion_factor": 0.01,
        "unit_of_measurement": ELECTRIC_CURRENT_AMPERE,
        "device_class": SensorDeviceClass.CURRENT,
        "state_class": STATE_CLASS_MEASUREMENT,
    },
    {
        "name": "Port 2 Power",
        "attribute_name": "port_state[1].pv_power",
        "conversion_factor": 0.1,
        "unit_of_measurement": POWER_WATT,
        "device_class": SensorDeviceClass.POWER,
        "state_class": STATE_CLASS_MEASUREMENT,
    },
    {
        "name": "Port 2 Energy Total",
        "attribute_name": "port_state[1].pv_energy_total",
        "conversion_factor": None,
        "unit_of_measurement": ENERGY_WATT_HOUR,
        "device_class": SensorDeviceClass.ENERGY,
        "state_class": STATE_CLASS_TOTAL_INCREASING,
    },
    {
        "name": "Port 2 Daily Yield",
        "attribute_name": "port_state[1].pv_daily_yield",
        "conversion_factor": None,
        "unit_of_measurement": ENERGY_WATT_HOUR,
        "device_class": SensorDeviceClass.ENERGY,
        "state_class": STATE_CLASS_TOTAL_INCREASING,
    },
]


async def async_setup_entry(hass, entry, async_add_devices):
    """Setup sensor platform."""
    hass_data = hass.data[DOMAIN][entry.entry_id]
    coordinator = hass_data[HASS_DATA_COORDINATOR]
    sensors = []

    for sensor_data in HOYMILES_SENSORS:
        sensors.append(HoymilesDataSensorEntity(coordinator, entry, sensor_data))

    async_add_devices(sensors)


def get_hoymiles_unique_id(config_entry_id: str, key: str, serial_number: str) -> str:
    """Create a uniqe id for a SunSpec entity"""
    return f"hoymiles_{config_entry_id}_{key}-{serial_number}"


class HoymilesDataSensorEntity(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, config_entry, data):
        """Pass coordinator to CoordinatorEntity."""
        super().__init__(coordinator, config_entry)
        self._config_entry = config_entry

        self._sensor_prefix = f'{config_entry.data.get(CONF_SENSOR_PREFIX)} ' if config_entry.data.get(CONF_SENSOR_PREFIX) else ""
        self._name = f'{self._sensor_prefix}{data["name"]}'
        self._attribute_name = data["attribute_name"]
        self._conversion_factor = data["conversion_factor"]
        self._unit_of_measurement = data["unit_of_measurement"]
        self._device_class = data["device_class"]
        self._state_class = data["state_class"]
        self._value = None
        self._uniqe_id = f"hoymiles_{self._attribute_name}"

        self._dtu_sn = ""

        if self.coordinator is not None and hasattr(self.coordinator, "data"):
            self._dtu_sn = getattr(self.coordinator.data, "dtu_sn", "")

        self._uniqe_id = get_hoymiles_unique_id(config_entry.entry_id, self._attribute_name, self._dtu_sn)

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
        return self._uniqe_id
    
    @property
    def native_value(self):
        return self._native_value

    @property
    def native_unit_of_measurement(self):
        return self._unit_of_measurement

    @property
    def device_class(self):
        return self._device_class
    
    @property
    def state_class(self):
        return self._state_class
    
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
    

    def update_state_value(self):
        if self.coordinator is not None and (not hasattr(self.coordinator, "data") or self.coordinator.data == None):
            self._native_value = 0.0
        else:
            if "[" in self._attribute_name and "]" in self._attribute_name:
                # Extracting the list index and attribute dynamically
                attribute_name, index = self._attribute_name.split("[")
                index = int(index.split("]")[0])
                nested_attribute = self._attribute_name.split("].")[1] if "]." in self._attribute_name else None

                attribute = getattr(self.coordinator.data, attribute_name.split("[")[0], [])

                if index < len(attribute):
                    if nested_attribute is not None:
                        self._native_value = getattr(attribute[index], nested_attribute, None)
                    else:
                        self._native_value = attribute[index]
                else:
                    self._native_value = None
            else:
                self._native_value = getattr(self.coordinator.data, self._attribute_name, None)

            if self._conversion_factor != None:
                self._native_value *= self._conversion_factor             

