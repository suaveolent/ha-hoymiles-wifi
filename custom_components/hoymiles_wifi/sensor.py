"""Support for Hoymiles sensors."""

from dataclasses import dataclass
import datetime
from enum import Enum
import logging

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfFrequency,
    UnitOfPower,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
import hoymiles_wifi.utils

from .const import (
    DOMAIN,
    FCTN_GENERATE_DTU_VERSION_STRING,
    FCTN_GENERATE_INVERTER_HW_VERSION_STRING,
    FCTN_GENERATE_INVERTER_SW_VERSION_STRING,
    HASS_APP_INFO_COORDINATOR,
    HASS_CONFIG_COORDINATOR,
    HASS_DATA_COORDINATOR,
)
from .entity import HoymilesCoordinatorEntity

_LOGGER = logging.getLogger(__name__)


class ConversionAction(Enum):
    """Enumeration for conversion actions."""

    HEX = 1

@dataclass(frozen=True)
class HoymilesSensorEntityDescriptionMixin:
    """Mixin for required keys."""

@dataclass(frozen=True)
class HoymilesSensorEntityDescription(SensorEntityDescription):
    """Describes Hoymiles data sensor entity."""

    conversion_factor: float = None
    reset_at_midnight: bool = False
    version_translation_function: str = None
    version_prefix: str = None
    is_dtu_sensor: bool = False


@dataclass(frozen=True)
class HoymilesDiagnosticEntityDescription(SensorEntityDescription):
    """Describes Hoymiles diagnostic sensor entity."""

    conversion: ConversionAction = None
    separator: str = None
    is_dtu_sensor: bool = False


HOYMILES_SENSORS = [
    HoymilesSensorEntityDescription(
        key="dtu_power",
        translation_key="ac_power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,

    ),
    HoymilesSensorEntityDescription(
        key="dtu_daily_energy",
        translation_key="ac_daily_energy",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        reset_at_midnight=True,
    ),
    HoymilesSensorEntityDescription(
        key="sgs_data[0].voltage",
        translation_key="grid_voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
    ),
    HoymilesSensorEntityDescription(
        key="sgs_data[0].frequency",
        translation_key="grid_frequency",
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        device_class=SensorDeviceClass.FREQUENCY,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.01,
    ),
    HoymilesSensorEntityDescription(
        key="sgs_data[0].temperature",
        translation_key="inverter_temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
    ),
    HoymilesSensorEntityDescription(
        key="pv_data[0].voltage",
        translation_key="port_1_dc_voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
    ),
    HoymilesSensorEntityDescription(
        key="pv_data[0].current",
        translation_key="port_1_dc_current",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.01,
    ),
    HoymilesSensorEntityDescription(
        key="pv_data[0].power",
        translation_key="port_1_dc_power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
    ),
    HoymilesSensorEntityDescription(
        key="pv_data[0].energy_total",
        translation_key="port_1_dc_total_energy",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    HoymilesSensorEntityDescription(
        key="pv_data[0].energy_daily",
        translation_key="port_1_dc_daily_energy",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        reset_at_midnight=True,
    ),
    HoymilesSensorEntityDescription(
        key="pv_data[1].voltage",
        translation_key="port_2_dc_voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
    ),
    HoymilesSensorEntityDescription(
        key="pv_data[1].current",
        translation_key="port_2_dc_current",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.01,
    ),
    HoymilesSensorEntityDescription(
        key="pv_data[1].power",
        translation_key="port_2_dc_power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
    ),
    HoymilesSensorEntityDescription(
        key="pv_data[1].energy_total",
        translation_key="port_2_dc_total_energy",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    HoymilesSensorEntityDescription(
        key="pv_data[1].energy_daily",
        translation_key="port_2_dc_daily_energy",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        reset_at_midnight=True,
    ),
]

CONFIG_DIAGNOSTIC_SENSORS = [
    HoymilesDiagnosticEntityDescription(
        key="wifi_ssid",
        translation_key="wifi_ssid",
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:wifi",
        is_dtu_sensor=True,
    ),
    HoymilesDiagnosticEntityDescription(
        key="meter_kind",
        translation_key="meter_kind",
        entity_category=EntityCategory.DIAGNOSTIC,
        is_dtu_sensor=True,
    ),
    HoymilesDiagnosticEntityDescription(
        key="wifi_mac_[0-5]",
        translation_key="mac_address",
        entity_category=EntityCategory.DIAGNOSTIC,
        separator=":",
        conversion= ConversionAction.HEX,
        is_dtu_sensor=True,
    ),
    HoymilesDiagnosticEntityDescription(
        key="wifi_ip_addr_[0-3]",
        translation_key="ip_address",
        entity_category=EntityCategory.DIAGNOSTIC,
        separator=".",
        is_dtu_sensor=True,
    ),
    HoymilesDiagnosticEntityDescription(
        key="dtu_ap_ssid",
        translation_key="dtu_ap_ssid",
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:access-point",
        is_dtu_sensor=True,
    ),
]

APP_INFO_SENSORS: tuple[HoymilesSensorEntityDescription, ...] = (
    HoymilesSensorEntityDescription(
        key = "dtu_info.dtu_sw_version",
        translation_key="dtu_sw_version",
        entity_category=EntityCategory.DIAGNOSTIC,
        version_translation_function=FCTN_GENERATE_DTU_VERSION_STRING,
        version_prefix="V",
        is_dtu_sensor=True,
    ),
    HoymilesSensorEntityDescription(
        key = "dtu_info.dtu_hw_version",
        translation_key="dtu_hw_version",
        entity_category=EntityCategory.DIAGNOSTIC,
        version_translation_function=FCTN_GENERATE_DTU_VERSION_STRING,
        version_prefix="H",
        is_dtu_sensor=True,

    ),
    HoymilesSensorEntityDescription(
        key = "pv_info[0].pv_sw_version",
        translation_key="pv_sw_version",
        entity_category=EntityCategory.DIAGNOSTIC,
        version_translation_function=FCTN_GENERATE_INVERTER_SW_VERSION_STRING,
        version_prefix="V"
    ),
    HoymilesSensorEntityDescription(
        key = "pv_info[0].pv_hw_version",
        translation_key="pv_hw_version",
        entity_category=EntityCategory.DIAGNOSTIC,
        version_translation_function=FCTN_GENERATE_INVERTER_HW_VERSION_STRING,
        version_prefix="H"
    ),
    HoymilesSensorEntityDescription(
        key = "dtu_info.signal_strength",
        translation_key="signal_strength",
        native_unit_of_measurement=PERCENTAGE,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:wifi",
        is_dtu_sensor=True,
    ),

)



async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensor platform."""

    hass_data = hass.data[DOMAIN][entry.entry_id]
    data_coordinator = hass_data[HASS_DATA_COORDINATOR]
    config_coordinator = hass_data[HASS_CONFIG_COORDINATOR]
    app_info_coordinator = hass_data[HASS_APP_INFO_COORDINATOR]
    sensors = []

    # Real Data Sensors
    for description in HOYMILES_SENSORS:
        device_class = description.device_class
        if device_class == SensorDeviceClass.ENERGY:
            energy_sensor = HoymilesEnergySensorEntity(entry, description, data_coordinator)
            sensors.append(energy_sensor)
        else:
            sensors.append(HoymilesDataSensorEntity(entry, description, data_coordinator))

    # Diagnostic Sensors
    for description in CONFIG_DIAGNOSTIC_SENSORS:
        sensors.append(HoymilesDiagnosticSensorEntity(entry, description, config_coordinator))

    for description in APP_INFO_SENSORS:
        sensors.append(HoymilesDataSensorEntity(entry, description, app_info_coordinator))

    async_add_entities(sensors)


class HoymilesDataSensorEntity(HoymilesCoordinatorEntity, SensorEntity):
    """Represents a sensor entity for Hoymiles data."""

    def __init__(self, config_entry: ConfigEntry, description: HoymilesSensorEntityDescription, coordinator: HoymilesCoordinatorEntity):
        """Pass coordinator to CoordinatorEntity."""
        super().__init__(config_entry, description, coordinator)

        self._attribute_name = description.key
        self._conversion_factor = description.conversion_factor
        self._version_translation_function = description.version_translation_function
        self._version_prefix = description.version_prefix
        self._native_value = None
        self._assumed_state = False

        self.update_state_value()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.update_state_value()
        super()._handle_coordinator_update()


    @property
    def native_value(self):
        """Return the native value of the sensor."""
        return self._native_value

    @property
    def assumed_state(self):
        """Return the assumed state of the sensor."""
        return self._assumed_state


    def update_state_value(self):
        """Update the state value of the sensor based on the coordinator data."""
        if self.coordinator is not None and (not hasattr(self.coordinator, "data") or self.coordinator.data is None):
            self._native_value = 0.0
        elif "[" in self._attribute_name and "]" in self._attribute_name:
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
        elif "." in self._attribute_name:
            attribute_parts = self._attribute_name.split(".")
            attribute = self.coordinator.data
            for part in attribute_parts:
                attribute = getattr(attribute, part, None)
            self._native_value = attribute

        else:
            self._native_value = getattr(self.coordinator.data, self._attribute_name, None)


        if self._native_value is not None and self._conversion_factor is not None:
            self._native_value *= self._conversion_factor

        if(self._native_value is not None and self._version_translation_function is not None):
            self._native_value = getattr(hoymiles_wifi.utils, self._version_translation_function)(int(self._native_value))

        if(self._native_value is not None and self._version_prefix is not None):
            self._native_value = f"{self._version_prefix}{self._native_value}"

class HoymilesEnergySensorEntity(HoymilesDataSensorEntity, RestoreSensor):
    """Represents an energy sensor entity for Hoymiles data."""

    def __init__(self, config_entry: ConfigEntry, description: HoymilesDiagnosticEntityDescription, coordinator: HoymilesCoordinatorEntity):
        """Initialize the HoymilesEnergySensorEntity."""
        super().__init__(config_entry, description, coordinator)
        # Important to set to None to not mess with long term stats
        self._last_known_value = None


    def schedule_midnight_reset(self, reset_sensor_value: bool = True):
        """Schedule the reset function to run again at the next midnight."""
        now = datetime.datetime.now()
        midnight = datetime.datetime.combine(now.date(), datetime.time(0, 0))
        midnight = midnight + datetime.timedelta(days=1) if now > midnight else midnight
        time_until_midnight = (midnight - datetime.datetime.now()).total_seconds()

        if reset_sensor_value:
            self.reset_sensor_value()

        self.hass.loop.call_later(time_until_midnight, self.schedule_midnight_reset)

    def reset_sensor_value(self):
        """Reset the sensor value."""
        self._last_known_value = 0

    @property
    def native_value(self):
        """Return the native value of the sensor."""
        super_native_value = super().native_value
        # For an energy sensor a value of 0 would mess up long term stats because of how total_increasing works
        if super_native_value == 0.0:
            _LOGGER.debug(
                "Returning last known value instead of 0.0 for %s to avoid resetting total_increasing counter", self.name
            )
            self._assumed_state = True
            return self._last_known_value
        self._last_known_value = super_native_value
        self._assumed_state = False
        return super_native_value

    async def async_added_to_hass(self) -> None:
        """Call when entity about to be added to hass."""
        await super().async_added_to_hass()

        state = await self.async_get_last_sensor_data()
        if state:
            self.last_known_value = state.native_value

        if self.entity_description.reset_at_midnight:
            self.schedule_midnight_reset(reset_sensor_value=False)


class HoymilesDiagnosticSensorEntity(HoymilesCoordinatorEntity, RestoreSensor, SensorEntity):
    """Represents a diagnostic sensor entity for Hoymiles data."""

    def __init__(self, config_entry, description, coordinator):
        """Initialize the HoymilesSensorEntity."""
        super().__init__(config_entry, description, coordinator)

        self._attribute_name = description.key
        self._conversion = description.conversion
        self._separator = description.separator
        self._native_value = None
        self._assumed_state = False

        self.update_state_value()
        self._last_known_value = self._native_value


    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.update_state_value()
        super()._handle_coordinator_update()

    @property
    def native_value(self):
        """Return the native value of the sensor."""
        if self._native_value is None:
            self._assumed_state = True
            return self._last_known_value

        self._last_known_value = self._native_value
        self._assumed_state = False
        return self._native_value


    def update_state_value(self):
        """Update the state value of the sensor."""

        if "[" in self._attribute_name and "]" in self._attribute_name:
            attribute_parts = self._attribute_name.split("[")
            attribute_name = attribute_parts[0]
            index_range = attribute_parts[1].split("]")[0]
            start, end = map(int, index_range.split('-'))

            new_attribute_names = [f"{attribute_name}{i}" for i in range(start, end + 1)]
            attribute_values = [str(getattr(self.coordinator.data, attr, "")) for attr in new_attribute_names]

            if("" in attribute_values):
                self._native_value = None
            else:
                self._native_value = self._separator.join(attribute_values)
        else:
            self._native_value =  getattr(self.coordinator.data, self._attribute_name, None)

        if(self._native_value is not None and self._conversion == ConversionAction.HEX):
            self._native_value = self._separator.join(hex(int(value))[2:] for value in self._native_value.split(self._separator)).upper()

    async def async_added_to_hass(self) -> None:
        """Call when entity about to be added to hass."""
        await super().async_added_to_hass()
        state = await self.async_get_last_sensor_data()
        if state:
            self.last_known_value = state.native_value

