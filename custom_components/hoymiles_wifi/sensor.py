import logging

from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
    RestoreSensor,
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
    EntityCategory,
)

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorDeviceClass,
)

from .const import (
    DOMAIN,
    HASS_DATA_COORDINATOR,
    HASS_CONFIG_COORDINATOR,
    CONVERSION_HEX,
)

from .entity import HoymilesCoordinatorEntity

from hoymiles_wifi.inverter import (
    Inverter,
    NetworkState
)


_LOGGER = logging.getLogger(__name__)

HOYMILES_SENSORS = [
    {
        "name": "AC Power",
        "attribute_name": "dtu_power",
        "conversion_factor": 0.1,
        "unit_of_measurement": POWER_WATT,
        "device_class": SensorDeviceClass.POWER,
        "state_class": STATE_CLASS_MEASUREMENT,
    },
    {
        "name": "AC Daily Energy",
        "attribute_name": "dtu_daily_energy",
        "conversion_factor": None,
        "unit_of_measurement": ENERGY_WATT_HOUR,
        "device_class": SensorDeviceClass.ENERGY,
        "state_class": STATE_CLASS_TOTAL_INCREASING,
    },
    {
        "name": "Grid Voltage",
        "attribute_name": "sgs_data[0].voltage",
        "conversion_factor": 0.1,
        "unit_of_measurement": ELECTRIC_POTENTIAL_VOLT,
        "device_class": SensorDeviceClass.VOLTAGE,
        "state_class": STATE_CLASS_MEASUREMENT,
    },
    {
        "name": "Grid Frequency",
        "attribute_name": "sgs_data[0].frequency",
        "conversion_factor": 0.01,
        "unit_of_measurement": FREQUENCY_HERTZ,
        "device_class": SensorDeviceClass.FREQUENCY,
        "state_class": STATE_CLASS_MEASUREMENT,
    },
    {
        "name": "Inverter Temperature",
        "attribute_name": "sgs_data[0].temperature",
        "conversion_factor": 0.1,
        "unit_of_measurement": TEMP_CELSIUS,
        "device_class": SensorDeviceClass.TEMPERATURE,
        "state_class": STATE_CLASS_MEASUREMENT,
    },
    {
        "name": "Port 1 DC Voltage",
        "attribute_name": "pv_data[0].voltage",
        "conversion_factor": 0.1,
        "unit_of_measurement": ELECTRIC_POTENTIAL_VOLT,
        "device_class": SensorDeviceClass.VOLTAGE,
        "state_class": STATE_CLASS_MEASUREMENT,
    },
    {
        "name": "Port 1 DC Current",
        "attribute_name": "pv_data[0].current",
        "conversion_factor": 0.01,
        "unit_of_measurement": ELECTRIC_CURRENT_AMPERE,
        "device_class": SensorDeviceClass.CURRENT,
        "state_class": STATE_CLASS_MEASUREMENT,
    },
    {
        "name": "Port 1 DC Power",
        "attribute_name": "pv_data[0].power",
        "conversion_factor": 0.1,
        "unit_of_measurement": POWER_WATT,
        "device_class": SensorDeviceClass.POWER,
        "state_class": STATE_CLASS_MEASUREMENT,
    },
    {
        "name": "Port 1 DC Total Energy",
        "attribute_name": "pv_data[0].energy_total",
        "conversion_factor": None,
        "unit_of_measurement": ENERGY_WATT_HOUR,
        "device_class": SensorDeviceClass.ENERGY,
        "state_class": STATE_CLASS_TOTAL_INCREASING,
    },
    {
        "name": "Port 1 DC Daily Energy",
        "attribute_name": "pv_data[0].energy_daily",
        "conversion_factor": None,
        "unit_of_measurement": ENERGY_WATT_HOUR,
        "device_class": SensorDeviceClass.ENERGY,
        "state_class": STATE_CLASS_TOTAL_INCREASING,
    },
        {
        "name": "Port 2 DC Voltage",
        "attribute_name": "pv_data[1].voltage",
        "conversion_factor": 0.1,
        "unit_of_measurement": ELECTRIC_POTENTIAL_VOLT,
        "device_class": SensorDeviceClass.VOLTAGE,
        "state_class": STATE_CLASS_MEASUREMENT,
    },
    {
        "name": "Port 2 DC Current",
        "attribute_name": "pv_data[1].current",
        "conversion_factor": 0.01,
        "unit_of_measurement": ELECTRIC_CURRENT_AMPERE,
        "device_class": SensorDeviceClass.CURRENT,
        "state_class": STATE_CLASS_MEASUREMENT,
    },
    {
        "name": "Port 2 DC Power",
        "attribute_name": "pv_data[1].power",
        "conversion_factor": 0.1,
        "unit_of_measurement": POWER_WATT,
        "device_class": SensorDeviceClass.POWER,
        "state_class": STATE_CLASS_MEASUREMENT,
    },
    {
        "name": "Port 2 DC Total Energy",
        "attribute_name": "pv_data[1].energy_total",
        "conversion_factor": None,
        "unit_of_measurement": ENERGY_WATT_HOUR,
        "device_class": SensorDeviceClass.ENERGY,
        "state_class": STATE_CLASS_TOTAL_INCREASING,
    },
    {
        "name": "Port 2 DC Daily Energy",
        "attribute_name": "pv_data[1].energy_daily",
        "conversion_factor": None,
        "unit_of_measurement": ENERGY_WATT_HOUR,
        "device_class": SensorDeviceClass.ENERGY,
        "state_class": STATE_CLASS_TOTAL_INCREASING,
    },
]


CONFIG_DIAGNOSTIC_SENSORS = [
    {
        "name": "Wi-Fi SSID",
        "attribute_name": "wifi_ssid",
    },
    {
        "name": "Meter Kind",
        "attribute_name": "meter_kind",
    },
    {
        "name": "MAC Address",
        "attribute_name": "wifi_mac_[0-5]",
        "separator": ":",
        "conversion": CONVERSION_HEX,
    },
    {
        "name": "IP Address",
        "attribute_name": "wifi_ip_addr_[0-3]",
        "separator": ".",
    },
    {
        "name": "DTU AP SSID",
        "attribute_name": "dtu_ap_ssid",
    },
]

async def async_setup_entry(hass, entry, async_add_devices):
    """Setup sensor platform."""
    hass_data = hass.data[DOMAIN][entry.entry_id]
    data_coordinator = hass_data[HASS_DATA_COORDINATOR]
    config_coordinator = hass_data[HASS_CONFIG_COORDINATOR] 
    sensors = []

    # Sensors
    for sensor_data in HOYMILES_SENSORS:      
        device_class = sensor_data["device_class"]
        if device_class == SensorDeviceClass.ENERGY:
            sensors.append(HoymilesEnergySensorEntity(data_coordinator, entry, sensor_data))
        else:
            sensors.append(HoymilesDataSensorEntity(data_coordinator, entry, sensor_data))

    # Inverter State
    sensors.append(HoymilesInverterSensorEntity(data_coordinator, entry, {"name": "Inverter"}))

    # Diagnostic Sensors
    for sensor_data in CONFIG_DIAGNOSTIC_SENSORS:      
        sensors.append(HoymilesDiagnosticSensorEntity(config_coordinator, entry, sensor_data))

    async_add_devices(sensors)


def get_hoymiles_unique_id(config_entry_id: str, key: str) -> str:
    """Create a _unique_id id for a Hoymiles entity"""
    return f"hoymiles_{config_entry_id}_{key}"


class HoymilesDataSensorEntity(HoymilesCoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, config_entry, data):
        """Pass coordinator to CoordinatorEntity."""
        super().__init__(coordinator, config_entry, data)

        self._name = f'{self._sensor_prefix}{data["name"]}'
        self._attribute_name = data["attribute_name"]
        self._conversion_factor = data["conversion_factor"]
        self._unit_of_measurement = data["unit_of_measurement"]
        self._device_class = data["device_class"]
        self._state_class = data["state_class"]
        self._value = None
        self._unique_id = f"hoymiles_{self._attribute_name}"
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
    def assumed_state(self):
        return self._assumed_state
    
    
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

            if self._native_value != None and self._conversion_factor != None:
                self._native_value *= self._conversion_factor

class HoymilesEnergySensorEntity(HoymilesDataSensorEntity, RestoreSensor):    

    def __init__(self, coordinator, config_entry, data):
        super().__init__(coordinator, config_entry, data)
        self._last_known_value = None
    

    @property
    def native_value(self):
        super_native_value = super().native_value
        # For an energy sensor a value of 0 woulld mess up long term stats because of how total_increasing works
        if super_native_value == 0.0:
            _LOGGER.debug(
                "Returning last known value instead of 0.0 for {self.name) to avoid resetting total_increasing counter"
            )
            self._assumed_state = True
            return self._last_known_value
        self._last_known_value = super_native_value
        self._assumed_state = False
        return super_native_value

    async def async_added_to_hass(self) -> None:
        """Call when entity about to be added to hass."""
        await super().async_added_to_hass()
        _LOGGER.debug(f"{self.name} Fetch last known state")
        state = await self.async_get_last_sensor_data()
        if state:
            _LOGGER.debug(
                f"{self.name} Got last known value from state: {state.native_value}"
            )
            self.last_known_value = state.native_value
        else:
            _LOGGER.debug(f"{self.name} No previous state was found")   



class HoymilesDiagnosticSensorEntity(HoymilesCoordinatorEntity, SensorEntity):

    def __init__(self, coordinator, config_entry, data):
        super().__init__(coordinator, config_entry, data)

        self._name = data["name"]
        self._attribute_name = data["attribute_name"]
        self._unique_id = get_hoymiles_unique_id(config_entry.entry_id, self._attribute_name)
        self._conversion = data["conversion"] if "conversion" in data else None
        self._separator = data["separator"] if "separator" in data else None
        self._native_value = None

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
    def native_value(self):
        return self._native_value
    
    @property
    def unique_id(self):
        return self._unique_id
    
    @property
    def entity_category(self):
        return EntityCategory.DIAGNOSTIC
    
    def update_state_value(self):
        
        if "[" in self._attribute_name and "]" in self._attribute_name:
            attribute_parts = self._attribute_name.split("[")
            attribute_name = attribute_parts[0]
            index_range = attribute_parts[1].split("]")[0]
            start, end = map(int, index_range.split('-'))

            new_attribute_names = [f"{attribute_name}{i}" for i in range(start, end + 1)]
            attribute_values = [str(getattr(self.coordinator.data, attr, "")) for attr in new_attribute_names]

            if("" in attribute_values):
                combined_value = None
            else:
                combined_value = self._separator.join(attribute_values)

            if(combined_value != None and self._conversion == CONVERSION_HEX):
                combined_value = self._separator.join(hex(int(value))[2:] for value in combined_value.split(self._separator)).upper()
            self._native_value = combined_value
        else:
            self._native_value =  getattr(self.coordinator.data, self._attribute_name, None)

class HoymilesInverterSensorEntity(HoymilesCoordinatorEntity, BinarySensorEntity):

    def __init__(self, coordinator, config_entry, data):
        super().__init__(coordinator, config_entry, data)

        self._name = data["name"]
        self._unique_id = get_hoymiles_unique_id(config_entry.entry_id, "inverter")
        self._inverter = self.coordinator.get_inverter()
        self._native_value = False
        self._device_class = BinarySensorDeviceClass.CONNECTIVITY

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
    def is_on(self):
        return self._native_value
    
    @property
    def unique_id(self):
        return self._unique_id
    
    @property
    def entity_category(self):
        return EntityCategory.DIAGNOSTIC
    
    @property
    def device_class(self):
        return self._device_class

    def update_state_value(self):
        inverter_state = self._inverter.get_state()
        if inverter_state == NetworkState.Online:
            self._native_value = True
        else:
            self._native_value = False




