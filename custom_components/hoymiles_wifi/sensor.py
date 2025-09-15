"""Support for Hoymiles sensors."""

import dataclasses
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from enum import Enum
import logging
import re

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
    UnitOfReactivePower,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
import hoymiles_wifi.hoymiles
from hoymiles_wifi.hoymiles import DTUType, get_dtu_model_type

from .const import (
    CONF_DTU_SERIAL_NUMBER,
    CONF_INVERTERS,
    CONF_HYBRID_INVERTERS,
    CONF_METERS,
    CONF_PORTS,
    CONF_THREE_PHASE_INVERTERS,
    DOMAIN,
    FCTN_GENERATE_DTU_VERSION_STRING,
    FCTN_GENERATE_INVERTER_HW_VERSION_STRING,
    FCTN_GENERATE_INVERTER_SW_VERSION_STRING,
    HASS_APP_INFO_COORDINATOR,
    HASS_CONFIG_COORDINATOR,
    HASS_DATA_COORDINATOR,
    HASS_ENERGY_STORAGE_DATA_COORDINATOR,
)
from .entity import (
    HoymilesCoordinatorEntity,
    HoymilesEntityDescription,
    DeviceType,
)

_LOGGER = logging.getLogger(__name__)


class ConversionAction(Enum):
    """Enumeration for conversion actions."""

    HEX = 1


@dataclass(frozen=True)
class HoymilesSensorEntityDescriptionMixin:
    """Mixin for required keys."""


@dataclass(frozen=True)
class HoymilesSensorEntityDescription(
    HoymilesEntityDescription, SensorEntityDescription
):
    """Describes Hoymiles data sensor entity."""

    conversion_factor: float = None
    reset_at_midnight: bool = False
    version_translation_function: str = None
    version_prefix: str = None
    assume_state: bool = False
    requires_device_type: int = DeviceType.ALL_DEVICES
    force_keep_maximum_within_day: bool = False


@dataclass(frozen=True)
class HoymilesEnergyStorageSensorEntityDescription(
    HoymilesEntityDescription, SensorEntityDescription
):
    """Describes Hoymiles energy storage data sensor entity."""

    model_name: str = None
    conversion_factor: float = None
    reset_at_midnight: bool = False
    version_translation_function: str = None
    version_prefix: str = None
    assume_state: bool = False
    force_keep_maximum_within_day: bool = False


@dataclass(frozen=True)
class HoymilesDiagnosticEntityDescription(
    HoymilesEntityDescription, SensorEntityDescription
):
    """Describes Hoymiles diagnostic sensor entity."""

    conversion: ConversionAction = None
    separator: str = None


HOYMILES_SENSORS = [
    HoymilesSensorEntityDescription(
        key="dtu_power",
        translation_key="ac_active_power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
        is_dtu_sensor=True,
        supported_dtu_types=[
            DTUType.DTU_G100,
            DTUType.DTU_W100,
            DTUType.DTU_LITE_S,
            DTUType.DTU_LITE,
            DTUType.DTU_PRO,
            DTUType.DTU_PRO_S,
            DTUType.DTUBI,
            DTUType.DTU_W_LITE,
        ],
    ),
    HoymilesSensorEntityDescription(
        key="dtu_daily_energy",
        translation_key="ac_daily_energy",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        reset_at_midnight=True,
        force_keep_maximum_within_day=True,
        is_dtu_sensor=True,
        supported_dtu_types=[
            DTUType.DTU_G100,
            DTUType.DTU_W100,
            DTUType.DTU_LITE_S,
            DTUType.DTU_LITE,
            DTUType.DTU_PRO,
            DTUType.DTU_PRO_S,
            DTUType.DTUBI,
            DTUType.DTU_W_LITE,
        ],
    ),
    HoymilesSensorEntityDescription(
        key="sgs_data[<inverter_count>].active_power",
        translation_key="ac_active_power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
    ),
    HoymilesSensorEntityDescription(
        key="sgs_data[<inverter_count>].reactive_power",
        translation_key="ac_reactive_power",
        native_unit_of_measurement=UnitOfReactivePower.VOLT_AMPERE_REACTIVE,
        device_class=SensorDeviceClass.REACTIVE_POWER,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
    ),
    HoymilesSensorEntityDescription(
        key="sgs_data[<inverter_count>].voltage",
        translation_key="grid_voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
    ),
    HoymilesSensorEntityDescription(
        key="sgs_data[<inverter_count>].current",
        translation_key="ac_current",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.01,
    ),
    HoymilesSensorEntityDescription(
        key="sgs_data[<inverter_count>].frequency",
        translation_key="grid_frequency",
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        device_class=SensorDeviceClass.FREQUENCY,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.01,
    ),
    HoymilesSensorEntityDescription(
        key="sgs_data[<inverter_count>].power_factor",
        translation_key="inverter_power_factor",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.POWER_FACTOR,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
    ),
    HoymilesSensorEntityDescription(
        key="sgs_data[<inverter_count>].temperature",
        translation_key="inverter_temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
    ),
    HoymilesSensorEntityDescription(
        key="sgs_data[<inverter_count>].warning_number",
        translation_key="inverter_warning_number",
    ),
    HoymilesSensorEntityDescription(
        key="tgs_data[<inverter_count>].active_power",
        translation_key="ac_active_power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
    ),
    HoymilesSensorEntityDescription(
        key="tgs_data[<inverter_count>].reactive_power",
        translation_key="ac_reactive_power",
        native_unit_of_measurement=UnitOfReactivePower.VOLT_AMPERE_REACTIVE,
        device_class=SensorDeviceClass.REACTIVE_POWER,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
    ),
    HoymilesSensorEntityDescription(
        key="tgs_data[<inverter_count>].voltage_phase_A",
        translation_key="voltage_phase_A",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
    ),
    HoymilesSensorEntityDescription(
        key="tgs_data[<inverter_count>].voltage_phase_B",
        translation_key="voltage_phase_B",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
    ),
    HoymilesSensorEntityDescription(
        key="tgs_data[<inverter_count>].voltage_phase_C",
        translation_key="voltage_phase_C",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
    ),
    HoymilesSensorEntityDescription(
        key="tgs_data[<inverter_count>].voltage_line_AB",
        translation_key="voltage_line_AB",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
    ),
    HoymilesSensorEntityDescription(
        key="tgs_data[<inverter_count>].voltage_line_BC",
        translation_key="voltage_line_BC",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
    ),
    HoymilesSensorEntityDescription(
        key="tgs_data[<inverter_count>].voltage_line_CA",
        translation_key="voltage_line_CA",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
    ),
    HoymilesSensorEntityDescription(
        key="tgs_data[<inverter_count>].frequency",
        translation_key="grid_frequency",
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        device_class=SensorDeviceClass.FREQUENCY,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.01,
    ),
    HoymilesSensorEntityDescription(
        key="tgs_data[<inverter_count>.current_phase_A",
        translation_key="current_phase_A",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.01,
    ),
    HoymilesSensorEntityDescription(
        key="tgs_data[<inverter_count>.current_phase_B",
        translation_key="current_phase_B",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.01,
    ),
    HoymilesSensorEntityDescription(
        key="tgs_data[<inverter_count>.current_phase_C",
        translation_key="current_phase_C",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.01,
    ),
    HoymilesSensorEntityDescription(
        key="tgs_data[<inverter_count>].power_factor",
        translation_key="inverter_power_factor",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.POWER_FACTOR,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
    ),
    HoymilesSensorEntityDescription(
        key="tgs_data[<inverter_count>].temperature",
        translation_key="inverter_temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
    ),
    HoymilesSensorEntityDescription(
        key="tgs_data[<inverter_count>].warning_number",
        translation_key="inverter_warning_number",
    ),
    HoymilesSensorEntityDescription(
        key="pv_data[<pv_count>].voltage",
        translation_key="port_dc_voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
    ),
    HoymilesSensorEntityDescription(
        key="pv_data[<pv_count>].current",
        translation_key="port_dc_current",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.01,
    ),
    HoymilesSensorEntityDescription(
        key="pv_data[<pv_count>].power",
        translation_key="port_dc_power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
    ),
    HoymilesSensorEntityDescription(
        key="pv_data[<pv_count>].energy_total",
        translation_key="port_dc_total_energy",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    HoymilesSensorEntityDescription(
        key="pv_data[<pv_count>].energy_daily",
        translation_key="port_dc_daily_energy",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        reset_at_midnight=True,
    ),
    HoymilesSensorEntityDescription(
        key="pv_data[<pv_count>].error_code",
        translation_key="port_error_code",
    ),
    HoymilesSensorEntityDescription(
        key="meter_data[<meter_count>].phase_total_power",
        translation_key="phase_total_power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=10,
    ),
    HoymilesSensorEntityDescription(
        key="meter_data[<meter_count>].phase_A_power",
        translation_key="phase_A_power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=10,
    ),
    HoymilesSensorEntityDescription(
        key="meter_data[<meter_count>].phase_B_power",
        translation_key="phase_B_power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=10,
        requires_device_type=DeviceType.THREE_PHASE_METER,
    ),
    HoymilesSensorEntityDescription(
        key="meter_data[<meter_count>].phase_C_power",
        translation_key="phase_C_power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=10,
        requires_device_type=DeviceType.THREE_PHASE_METER,
    ),
    HoymilesSensorEntityDescription(
        key="meter_data[<meter_count>].power_factor_total",
        translation_key="power_factor_total",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.POWER_FACTOR,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
    ),
    HoymilesSensorEntityDescription(
        key="meter_data[<meter_count>].energy_total_power",
        translation_key="energy_total_power",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        conversion_factor=10.0,
    ),
    HoymilesSensorEntityDescription(
        key="meter_data[<meter_count>].energy_phase_A",
        translation_key="energy_phase_A",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        conversion_factor=10.0,
    ),
    HoymilesSensorEntityDescription(
        key="meter_data[<meter_count>].energy_phase_B",
        translation_key="energy_phase_B",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        requires_device_type=DeviceType.THREE_PHASE_METER,
        conversion_factor=10.0,
    ),
    HoymilesSensorEntityDescription(
        key="meter_data[<meter_count>].energy_phase_C",
        translation_key="energy_phase_C",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        requires_device_type=DeviceType.THREE_PHASE_METER,
        conversion_factor=10.0,
    ),
    HoymilesSensorEntityDescription(
        key="meter_data[<meter_count>].energy_total_consumed",
        translation_key="energy_total_consumed",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        conversion_factor=10.0,
    ),
    HoymilesSensorEntityDescription(
        key="meter_data[<meter_count>].energy_phase_A_consumed",
        translation_key="energy_phase_A_consumed",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        conversion_factor=10.0,
    ),
    HoymilesSensorEntityDescription(
        key="meter_data[<meter_count>].energy_phase_B_consumed",
        translation_key="energy_phase_B_consumed",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        requires_device_type=DeviceType.THREE_PHASE_METER,
        conversion_factor=10.0,
    ),
    HoymilesSensorEntityDescription(
        key="meter_data[<meter_count>].energy_phase_C_consumed",
        translation_key="energy_phase_C_consumed",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        requires_device_type=DeviceType.THREE_PHASE_METER,
        conversion_factor=10.0,
    ),
    HoymilesSensorEntityDescription(
        key="meter_data[<meter_count>].voltage_phase_A",
        translation_key="voltage_phase_A",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.01,
    ),
    HoymilesSensorEntityDescription(
        key="meter_data[<meter_count>].voltage_phase_B",
        translation_key="voltage_phase_B",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.01,
        requires_device_type=DeviceType.THREE_PHASE_METER,
    ),
    HoymilesSensorEntityDescription(
        key="meter_data[<meter_count>].voltage_phase_C",
        translation_key="voltage_phase_C",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.01,
        requires_device_type=DeviceType.THREE_PHASE_METER,
    ),
    HoymilesSensorEntityDescription(
        key="meter_data[<meter_count>].current_phase_A",
        translation_key="current_phase_A",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.01,
    ),
    HoymilesSensorEntityDescription(
        key="meter_data[<meter_count>].current_phase_B",
        translation_key="current_phase_B",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.01,
        requires_device_type=DeviceType.THREE_PHASE_METER,
    ),
    HoymilesSensorEntityDescription(
        key="meter_data[<meter_count>].current_phase_C",
        translation_key="current_phase_C",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.01,
        requires_device_type=DeviceType.THREE_PHASE_METER,
    ),
    HoymilesSensorEntityDescription(
        key="meter_data[<meter_count>].power_factor_phase_A",
        translation_key="power_factor_phase_A",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.POWER_FACTOR,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
    ),
    HoymilesSensorEntityDescription(
        key="meter_data[<meter_count>].power_factor_phase_B",
        translation_key="power_factor_phase_B",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.POWER_FACTOR,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
        requires_device_type=DeviceType.THREE_PHASE_METER,
    ),
    HoymilesSensorEntityDescription(
        key="meter_data[<meter_count>].power_factor_phase_C",
        translation_key="power_factor_phase_C",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.POWER_FACTOR,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
        requires_device_type=DeviceType.THREE_PHASE_METER,
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
        conversion=ConversionAction.HEX,
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
        key="dtu_info.dtu_sw_version",
        translation_key="dtu_sw_version",
        entity_category=EntityCategory.DIAGNOSTIC,
        version_translation_function=FCTN_GENERATE_DTU_VERSION_STRING,
        version_prefix="V",
        is_dtu_sensor=True,
        assume_state=True,
    ),
    HoymilesSensorEntityDescription(
        key="dtu_info.dtu_hw_version",
        translation_key="dtu_hw_version",
        entity_category=EntityCategory.DIAGNOSTIC,
        version_translation_function=FCTN_GENERATE_DTU_VERSION_STRING,
        version_prefix="H",
        is_dtu_sensor=True,
        assume_state=True,
    ),
    HoymilesSensorEntityDescription(
        key="pv_info[<inverter_count>].pv_sw_version",
        translation_key="pv_sw_version",
        entity_category=EntityCategory.DIAGNOSTIC,
        version_translation_function=FCTN_GENERATE_INVERTER_SW_VERSION_STRING,
        version_prefix="V",
        assume_state=True,
    ),
    HoymilesSensorEntityDescription(
        key="pv_info[<inverter_count>].pv_hw_version",
        translation_key="pv_hw_version",
        entity_category=EntityCategory.DIAGNOSTIC,
        version_translation_function=FCTN_GENERATE_INVERTER_HW_VERSION_STRING,
        version_prefix="H",
        assume_state=True,
    ),
    HoymilesSensorEntityDescription(
        key="dtu_info.signal_strength",
        translation_key="signal_strength",
        native_unit_of_measurement=PERCENTAGE,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:wifi",
        is_dtu_sensor=True,
    ),
)

HOYMILES_ENERGY_STORAGE_SENSORS = [
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].production.energy_to_load",
        translation_key="energy_to_load",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        conversion_factor=0.1,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].production.energy_to_battery",
        translation_key="energy_to_battery",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        conversion_factor=0.1,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].production.energy_to_grid",
        translation_key="energy_to_grid",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        conversion_factor=0.1,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].consumption.energy_from_pv",
        translation_key="energy_from_pv",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        conversion_factor=0.1,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].consumption.energy_from_battery",
        translation_key="energy_from_battery",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        conversion_factor=0.1,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].consumption.energy_from_grid",
        translation_key="energy_from_grid",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        conversion_factor=0.1,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].pv_panels[<pv_panel_count>].voltage",
        translation_key="pv_panel_voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].pv_panels[<pv_panel_count>].current",
        translation_key="pv_panel_current",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.01,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].pv_panels[<pv_panel_count>].power",
        translation_key="pv_panel_power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=1,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].pv_panels[<pv_panel_count>].energy",
        translation_key="pv_panel_energy",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        conversion_factor=0.1,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].battery_management.state_of_charge",
        translation_key="state_of_charge",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].battery_management.state_of_health",
        translation_key="state_of_health",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].battery_management.voltage",
        translation_key="battery_voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].battery_management.internal_charge_mode",
        translation_key="internal_charge_mode",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].battery_management.internal_discharge_mode",
        translation_key="internal_discharge_mode",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].battery_management.cell_voltage_high",
        translation_key="cell_voltage_high",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.01,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].battery_management.cell_voltage_low",
        translation_key="cell_voltage_low",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.001,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].battery_management.temp_high_charge",
        translation_key="temp_high_charge",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].battery_management.temp_low_charge",
        translation_key="temp_low_charge",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].battery_management.temp_high_module",
        translation_key="temp_high_module",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].battery_management.temp_low_module",
        translation_key="temp_low_module",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].battery_management.energy_charged",
        translation_key="energy_charged",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        conversion_factor=0.1,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].battery_management.energy_discharged",
        translation_key="energy_discharged",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        conversion_factor=0.1,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].battery_management.voltage_charge_high",
        translation_key="voltage_charge_high",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.001,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].battery_management.voltage_charge_low",
        translation_key="voltage_charge_low",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.001,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].battery_management.voltage_module_high",
        translation_key="voltage_module_high",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.01,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].battery_management.voltage_module_low",
        translation_key="voltage_module_low",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.01,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].grid.param.frequency",
        translation_key="grid_frequency",
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        device_class=SensorDeviceClass.FREQUENCY,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.01,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].grid.phases[<phase_count>].voltage",
        translation_key="grid_voltage_phase",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].grid.phases[<phase_count>].current",
        translation_key="grid_current_phase",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.001,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].grid.phases[<phase_count>].active_power",
        translation_key="grid_active_power_phase",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=1,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].grid.phases[<phase_count>].reactive_power",
        translation_key="grid_reactive_power_phase",
        native_unit_of_measurement=UnitOfReactivePower.VOLT_AMPERE_REACTIVE,
        device_class=SensorDeviceClass.REACTIVE_POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].grid.phases[<phase_count>].power_factor",
        translation_key="grid_power_factor_phase",
        native_unit_of_measurement=PERCENTAGE,
        device_class=None,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].grid.phases[<phase_count>].energy_frequency",
        translation_key="grid_energy_frequency_phase",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        conversion_factor=0.1,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].grid.phases[<phase_count>].energy_consumed",
        translation_key="grid_energy_consumed_phase",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        conversion_factor=0.1,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].load.param.status",
        translation_key="load_status",
        device_class=SensorDeviceClass.ENUM,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].load.param.frequency",
        translation_key="load_frequency",
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        device_class=SensorDeviceClass.FREQUENCY,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.01,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].load.phases[<phase_count>].voltage",
        translation_key="load_voltage_phase",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].load.phases[<phase_count>].active_power",
        translation_key="load_active_power_phase",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].load.phases[<phase_count>].energy_consumed",
        translation_key="load_energy_consumed_phase",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        conversion_factor=0.1,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].inverter.param.status",
        translation_key="inverter_status",
        device_class=SensorDeviceClass.ENUM,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].inverter.param.frequency",
        translation_key="inverter_frequency",
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        device_class=SensorDeviceClass.FREQUENCY,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.01,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].inverter.param.isolation_resistance",
        translation_key="inverter_isolation_resistance",
        native_unit_of_measurement="kΩ",
        device_class=None,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].inverter.param.leakage_current",
        translation_key="inverter_leakage_current",
        native_unit_of_measurement=UnitOfElectricCurrent.MILLIAMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].inverter.param.drm_signal",
        translation_key="inverter_drm_signal",
        device_class=SensorDeviceClass.ENUM,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].inverter.phases[<phase_count>].voltage",
        translation_key="inverter_voltage_phase",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].inverter.phases[<phase_count>].current",
        translation_key="inverter_current_phase",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.01,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].inverter.phases[<phase_count>].active_power",
        translation_key="inverter_active_power_phase",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].inverter.phases[<phase_count>].reactive_power",
        translation_key="inverter_reactive_power_phase",
        native_unit_of_measurement=UnitOfReactivePower.VOLT_AMPERE_REACTIVE,
        device_class=SensorDeviceClass.REACTIVE_POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].inverter.phases[<phase_count>].dc_current",
        translation_key="inverter_dc_current_phase",
        native_unit_of_measurement=UnitOfElectricCurrent.MILLIAMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].inverter.phases[<phase_count>].dc_voltage",
        translation_key="inverter_dc_voltage_phase",
        native_unit_of_measurement=UnitOfElectricPotential.MILLIVOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].inverter.phases[<phase_count>].eps_voltage",
        translation_key="inverter_eps_voltage_phase",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].inverter.phases[<phase_count>].eps_current",
        translation_key="inverter_eps_current_phase",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.01,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].inverter.phases[<phase_count>].eps_power",
        translation_key="inverter_eps_power_phase",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].pv_inverter.param.status",
        translation_key="pv_inverter_status",
        device_class=SensorDeviceClass.ENUM,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].pv_inverter.param.frequency",
        translation_key="pv_inverter_frequency",
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        device_class=SensorDeviceClass.FREQUENCY,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.01,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].pv_inverter.phases[<phase_count>].voltage",
        translation_key="pv_inverter_voltage_phase",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].pv_inverter.phases[<phase_count>].current",
        translation_key="pv_inverter_current_phase",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.01,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].pv_inverter.phases[<phase_count>].active_power",
        translation_key="pv_inverter_active_power_phase",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].pv_inverter.phases[<phase_count>].reactive_power",
        translation_key="pv_inverter_reactive_power_phase",
        native_unit_of_measurement=UnitOfReactivePower.VOLT_AMPERE_REACTIVE,
        device_class=SensorDeviceClass.REACTIVE_POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].pv_inverter.phases[<phase_count>].energy",
        translation_key="pv_inverter_energy_phase",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        conversion_factor=0.1,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].power_flow.pv_to_load",
        translation_key="pv_to_load",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].power_flow.pv_to_battery",
        translation_key="pv_to_battery",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].power_flow.pv_to_grid",
        translation_key="pv_to_grid",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].power_flow.battery_to_load",
        translation_key="battery_to_load",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].power_flow.grid_to_load",
        translation_key="grid_to_load",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HoymilesEnergyStorageSensorEntityDescription(
        key="[<inverter_count>].power_flow.battery_to_grid",
        translation_key="battery_to_grid",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
]


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensor platform."""

    hass_data = hass.data[DOMAIN][config_entry.entry_id]
    data_coordinator = hass_data.get(HASS_DATA_COORDINATOR, None)
    config_coordinator = hass_data.get(HASS_CONFIG_COORDINATOR, None)
    app_info_coordinator = hass_data.get(HASS_APP_INFO_COORDINATOR, None)
    energy_storage_data_coordinator = hass_data.get(
        HASS_ENERGY_STORAGE_DATA_COORDINATOR, None
    )
    dtu_serial_number = config_entry.data[CONF_DTU_SERIAL_NUMBER]
    single_phase_inverters = config_entry.data.get(CONF_INVERTERS, [])
    three_phase_inverters = config_entry.data.get(CONF_THREE_PHASE_INVERTERS, [])
    hybrid_inverters = config_entry.data.get(CONF_HYBRID_INVERTERS, [])
    meters = config_entry.data.get(CONF_METERS, [])
    inverters = single_phase_inverters + three_phase_inverters
    ports = config_entry.data[CONF_PORTS]
    sensors = []

    # Real Data Sensors

    if inverters:
        for description in HOYMILES_SENSORS:
            device_class = description.device_class
            if device_class == SensorDeviceClass.ENERGY:
                class_name = HoymilesEnergySensorEntity
            else:
                class_name = HoymilesDataSensorEntity

            if "sgs_data" in description.key and single_phase_inverters:
                sensor_entities = get_sensors_for_description(
                    config_entry,
                    description,
                    data_coordinator,
                    class_name,
                    dtu_serial_number,
                    single_phase_inverters,
                    [],
                )
                sensors.extend(sensor_entities)

            elif "tgs_data" in description.key and three_phase_inverters:
                sensor_entities = get_sensors_for_description(
                    config_entry,
                    description,
                    data_coordinator,
                    class_name,
                    dtu_serial_number,
                    three_phase_inverters,
                    [],
                )
                sensors.extend(sensor_entities)
            elif "meter" in description.key and meters:
                sensor_entities = get_sensors_for_description(
                    config_entry,
                    description,
                    data_coordinator,
                    class_name,
                    dtu_serial_number,
                    [],
                    [],
                    meters,
                )
                sensors.extend(sensor_entities)

            else:
                sensor_entities = get_sensors_for_description(
                    config_entry,
                    description,
                    data_coordinator,
                    class_name,
                    dtu_serial_number,
                    [],
                    ports,
                )
                sensors.extend(sensor_entities)

        for description in CONFIG_DIAGNOSTIC_SENSORS:
            sensor_entities = get_sensors_for_description(
                config_entry,
                description,
                config_coordinator,
                HoymilesDiagnosticSensorEntity,
                dtu_serial_number,
                inverters,
                ports,
            )
            sensors.extend(sensor_entities)

        for description in APP_INFO_SENSORS:
            sensor_entities = get_sensors_for_description(
                config_entry,
                description,
                app_info_coordinator,
                HoymilesDataSensorEntity,
                dtu_serial_number,
                inverters,
                ports,
            )
            sensors.extend(sensor_entities)

    if hybrid_inverters:
        for description in HOYMILES_ENERGY_STORAGE_SENSORS:
            sensor_entities = get_sensors_for_hybrid_inverter_description(
                config_entry,
                description,
                energy_storage_data_coordinator,
                HoymilesEnergyStorageSensorEntity,
                dtu_serial_number,
                hybrid_inverters,
            )
            sensors.extend(sensor_entities)

    async_add_entities(sensors)


def get_sensors_for_description(
    config_entry: ConfigEntry,
    description: SensorEntityDescription,
    coordinator: HoymilesCoordinatorEntity,
    class_name: SensorEntity,
    dtu_serial_number: str,
    inverters: list,
    ports: list,
    meters: list = [],
) -> list[SensorEntity]:
    """Get sensors for the given description."""

    sensors = []

    if "<inverter_count>" in description.key:
        for index, inverter_serial in enumerate(inverters):
            new_key = description.key.replace("<inverter_count>", str(index))
            updated_description = dataclasses.replace(
                description, key=new_key, serial_number=inverter_serial
            )
            sensor = class_name(config_entry, updated_description, coordinator)
            sensors.append(sensor)
    elif "<pv_count>" in description.key:
        for index, port in enumerate(ports):
            inverter_serial = port["inverter_serial_number"]
            port_number = port["port_number"]
            new_key = str(description.key).replace("<pv_count>", str(index))
            updated_description = dataclasses.replace(
                description,
                key=new_key,
                serial_number=inverter_serial,
                port_number=port_number,
            )
            sensor = class_name(config_entry, updated_description, coordinator)
            sensors.append(sensor)
    elif "meter_count" in description.key:
        for index, meter in enumerate(meters):
            meter_serial = meter["meter_serial_number"]
            meter_type = meter["device_type"]

            if description.requires_device_type.value in (
                DeviceType.ALL_DEVICES.value,
                meter_type,
            ):
                new_key = description.key.replace("<meter_count>", str(index))
                updated_description = dataclasses.replace(
                    description, key=new_key, serial_number=meter_serial
                )
                sensor = class_name(config_entry, updated_description, coordinator)
                sensors.append(sensor)
    else:
        if description.supported_dtu_types is not None:
            serial_bytes = bytes.fromhex(dtu_serial_number)

            dtu_type = None
            try:
                dtu_type = get_dtu_model_type(serial_bytes)
            except ValueError as e:
                _LOGGER.error(f"Error getting DTU model type: {e}")

        if (
            description.supported_dtu_types is None
            or dtu_type in description.supported_dtu_types
        ):
            updated_description = dataclasses.replace(
                description, serial_number=dtu_serial_number
            )
            sensor = class_name(config_entry, updated_description, coordinator)
            sensors.append(sensor)

    return sensors


def get_sensors_for_hybrid_inverter_description(
    config_entry: ConfigEntry,
    description: SensorEntityDescription,
    coordinator: HoymilesCoordinatorEntity,
    class_name: SensorEntity,
    dtu_serial_number: str,
    inverters: list,
) -> list[SensorEntity]:
    """Get sensors for the given description."""

    sensors = []

    if "<inverter_count>" in description.key:
        for index, inverter in enumerate(inverters):
            new_key = description.key.replace("<inverter_count>", str(index))

            if "<pv_panel_count>" in description.key:
                # TODO: Dynamically determine number of PV panels
                for pv_index in range(0, 2):
                    new_pv_index_key = new_key.replace(
                        "<pv_panel_count>", str(pv_index)
                    )
                    updated_description = dataclasses.replace(
                        description,
                        key=new_pv_index_key,
                        serial_number=inverter["inverter_serial_number"],
                        model_name=inverter["model_name"],
                        port_number=pv_index + 1,
                    )
                    sensor = class_name(config_entry, updated_description, coordinator)
                    sensors.append(sensor)
            elif "<phase_count>" in description.key:
                # TODO: Dynamically determine number of phases
                for phase_index in range(0, 3):
                    new_phase_index_key = new_key.replace(
                        "<phase_count>", str(phase_index)
                    )
                    updated_description = dataclasses.replace(
                        description,
                        key=new_phase_index_key,
                        serial_number=inverter["inverter_serial_number"],
                        model_name=inverter["model_name"],
                        phase=["A", "B", "C"][phase_index],
                    )
                    sensor = class_name(config_entry, updated_description, coordinator)
                    sensors.append(sensor)

            else:
                updated_description = dataclasses.replace(
                    description,
                    key=new_key,
                    serial_number=inverter["inverter_serial_number"],
                    model_name=inverter["model_name"],
                )
                sensor = class_name(config_entry, updated_description, coordinator)
                sensors.append(sensor)

    else:
        updated_description = dataclasses.replace(
            description, serial_number=dtu_serial_number
        )
        sensor = class_name(config_entry, updated_description, coordinator)
        sensors.append(sensor)

    return sensors


class HoymilesDataSensorEntity(HoymilesCoordinatorEntity, RestoreSensor):
    """Represents a sensor entity for Hoymiles data."""

    def __init__(
        self,
        config_entry: ConfigEntry,
        description: HoymilesSensorEntityDescription,
        coordinator: HoymilesCoordinatorEntity,
    ):
        """Pass coordinator to CoordinatorEntity."""
        super().__init__(config_entry, description, coordinator)

        self._attribute_name = description.key
        self._conversion_factor = description.conversion_factor
        self._version_translation_function = description.version_translation_function
        self._version_prefix = description.version_prefix
        self._native_value = None
        self._assumed_state = False
        self._last_known_value = None
        self._last_successful_update = None
        self._last_update_state = None

        self.update_state_value()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.update_state_value()
        super()._handle_coordinator_update()

    @property
    def native_value(self):
        """Return the native value of the sensor."""
        if self._native_value == 0.0:
            if self.entity_description.assume_state:
                return self._last_known_value
            elif (
                self._last_successful_update is not None
                and datetime.now() - self._last_successful_update
                <= timedelta(minutes=3)
            ):
                _LOGGER.debug(
                    "[%s] Returning last known value: %s, instead of 0.0 to cope with inverter in offline mode.",
                    self.name,
                    self._last_known_value,
                )
                self._assumed_state = True
                return self._last_known_value
        else:
            self._last_successful_update = datetime.now()
            self._last_known_value = self._native_value
        self._assumed_state = False
        return self._native_value

    @property
    def assumed_state(self):
        """Return the assumed state of the sensor."""
        return self._assumed_state

    def update_state_value(self):
        """Update the state value of the sensor based on the coordinator data."""
        new_native_value = 0.0

        if self.coordinator is not None and (
            not hasattr(self.coordinator, "data") or self.coordinator.data is None
        ):
            new_native_value = 0.0
        elif "[" in self._attribute_name and "]" in self._attribute_name:
            # Extracting the list index and attribute dynamically
            attribute_name, index = self._attribute_name.split("[")
            index = int(index.split("]")[0])
            nested_attribute = (
                self._attribute_name.split("].")[1]
                if "]." in self._attribute_name
                else None
            )

            attribute = getattr(self.coordinator.data, attribute_name.split("[")[0], [])

            if index < len(attribute):
                if nested_attribute is not None:
                    new_native_value = getattr(attribute[index], nested_attribute, None)
                else:
                    new_native_value = attribute[index]
            else:
                new_native_value = None
        elif "." in self._attribute_name:
            attribute_parts = self._attribute_name.split(".")
            attribute = self.coordinator.data
            for part in attribute_parts:
                attribute = getattr(attribute, part, None)
            new_native_value = attribute

        else:
            new_native_value = getattr(
                self.coordinator.data, self._attribute_name, None
            )

        if new_native_value is not None and self._conversion_factor is not None:
            new_native_value *= self._conversion_factor

        if (
            new_native_value is not None
            and new_native_value != 0.0
            and self._version_translation_function is not None
        ):
            new_native_value = getattr(
                hoymiles_wifi.hoymiles, self._version_translation_function
            )(int(new_native_value))

        if (
            new_native_value is not None
            and new_native_value != 0.0
            and self._version_prefix is not None
        ):
            new_native_value = f"{self._version_prefix}{new_native_value}"

        if (
            self.entity_description.force_keep_maximum_within_day
            and self._last_update_state is not None
            and self._last_update_state.date() == datetime.now().date()
        ):
            new_native_value = max(new_native_value, self._native_value)

        self._last_update_state = datetime.now()
        self._native_value = new_native_value

    async def async_added_to_hass(self) -> None:
        """Call when entity about to be added to hass."""
        await super().async_added_to_hass()

        state = await self.async_get_last_sensor_data()
        if state:
            self.last_known_value = state.native_value


class HoymilesEnergySensorEntity(HoymilesDataSensorEntity, RestoreSensor):
    """Represents an energy sensor entity for Hoymiles data."""

    def __init__(
        self,
        config_entry: ConfigEntry,
        description: HoymilesDiagnosticEntityDescription,
        coordinator: HoymilesCoordinatorEntity,
    ):
        """Initialize the HoymilesEnergySensorEntity."""
        super().__init__(config_entry, description, coordinator)
        # Important to set to None to not mess with long term stats
        self._last_known_value = None

    def schedule_midnight_reset(self, reset_sensor_value: bool = True):
        """Schedule the reset function to run again at the next midnight."""
        now = datetime.now()
        midnight = datetime.combine(now.date(), time(0, 0))
        midnight = midnight + timedelta(days=1) if now > midnight else midnight
        time_until_midnight = (midnight - datetime.now()).total_seconds()

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
                "Returning last known value instead of 0.0 for %s to avoid resetting total_increasing counter",
                self.name,
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
            self._last_known_value = state.native_value

        if self.entity_description.reset_at_midnight:
            self.schedule_midnight_reset(reset_sensor_value=False)


class HoymilesDiagnosticSensorEntity(
    HoymilesCoordinatorEntity, RestoreSensor, SensorEntity
):
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
            start, end = map(int, index_range.split("-"))

            new_attribute_names = [
                f"{attribute_name}{i}" for i in range(start, end + 1)
            ]
            attribute_values = [
                str(getattr(self.coordinator.data, attr, ""))
                for attr in new_attribute_names
            ]

            if "" in attribute_values:
                self._native_value = None
            else:
                self._native_value = self._separator.join(attribute_values)
        else:
            self._native_value = getattr(
                self.coordinator.data, self._attribute_name, None
            )

        if self._native_value is not None and self._conversion == ConversionAction.HEX:
            self._native_value = self._separator.join(
                hex(int(value))[2:]
                for value in self._native_value.split(self._separator)
            ).upper()

    async def async_added_to_hass(self) -> None:
        """Call when entity about to be added to hass."""
        await super().async_added_to_hass()
        state = await self.async_get_last_sensor_data()
        if state:
            self._last_known_value = state.native_value


class HoymilesEnergyStorageSensorEntity(HoymilesCoordinatorEntity, RestoreSensor):
    """Represents a sensor entity for Hoymiles data."""

    def __init__(
        self,
        config_entry: ConfigEntry,
        description: HoymilesEnergyStorageSensorEntityDescription,
        coordinator: HoymilesCoordinatorEntity,
    ):
        """Pass coordinator to CoordinatorEntity."""
        super().__init__(config_entry, description, coordinator)

        self._attribute_name = description.key
        self._conversion_factor = description.conversion_factor
        self._version_translation_function = description.version_translation_function
        self._version_prefix = description.version_prefix
        self._native_value = None
        self._assumed_state = False
        self._last_known_value = None
        self._last_successful_update = None
        self._last_update_state = None

        self.update_state_value()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.update_state_value()
        super()._handle_coordinator_update()

    @property
    def native_value(self):
        """Return the native value of the sensor."""
        if self._native_value == 0.0:
            if self.entity_description.assume_state:
                return self._last_known_value
            elif (
                self._last_successful_update is not None
                and datetime.now() - self._last_successful_update
                <= timedelta(minutes=3)
            ):
                _LOGGER.debug(
                    "[%s] Returning last known value: %s, instead of 0.0 to cope with inverter in offline mode.",
                    self.name,
                    self._last_known_value,
                )
                self._assumed_state = True
                return self._last_known_value
        else:
            self._last_successful_update = datetime.now()
            self._last_known_value = self._native_value
        self._assumed_state = False
        return self._native_value

    @property
    def assumed_state(self):
        """Return the assumed state of the sensor."""
        return self._assumed_state

    def update_state_value(self):
        """Update the state value of the sensor based on the coordinator data."""
        new_native_value = 0.0

        if (
            self.coordinator is None
            or not hasattr(self.coordinator, "data")
            or self.coordinator.data is None
        ):
            self._native_value = 0.0
            return

        def resolve_path(obj, path):
            tokens = re.findall(r"\w+|\[\d+\]", path)
            for token in tokens:
                if obj is None:
                    return None
                if token.startswith("["):
                    index = int(token[1:-1])
                    try:
                        obj = obj[index]
                    except (IndexError, TypeError):
                        logging.error(
                            "Index %d out of range for object: %s", index, obj
                        )
                        return None
                else:
                    obj = getattr(obj, token, None)
            return obj

        new_native_value = resolve_path(self.coordinator.data, self._attribute_name)

        if new_native_value is not None and self._conversion_factor is not None:
            new_native_value *= self._conversion_factor

        if (
            new_native_value is not None
            and new_native_value != 0.0
            and self._version_translation_function is not None
        ):
            new_native_value = getattr(
                hoymiles_wifi.hoymiles, self._version_translation_function
            )(int(new_native_value))

        if (
            new_native_value is not None
            and new_native_value != 0.0
            and self._version_prefix is not None
        ):
            new_native_value = f"{self._version_prefix}{new_native_value}"

        if (
            self.entity_description.force_keep_maximum_within_day
            and self._last_update_state is not None
            and self._last_update_state.date() == datetime.now().date()
        ):
            new_native_value = max(new_native_value, self._native_value)

        self._last_update_state = datetime.now()
        self._native_value = new_native_value

        async def async_added_to_hass(self) -> None:
            """Call when entity about to be added to hass."""
            await super().async_added_to_hass()

            state = await self.async_get_last_sensor_data()
            if state:
                self.last_known_value = state.native_value
