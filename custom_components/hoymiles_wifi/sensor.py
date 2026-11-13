"""Support for Hoymiles sensors."""

import dataclasses
from dataclasses import dataclass
from enum import Enum
import logging
import re

from google.protobuf.json_format import MessageToDict
from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorExtraStoredData,
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
    UnitOfReactivePower,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_change
from homeassistant.util import dt as dt_util
from hoymiles_wifi.dtu import NetworkState
import hoymiles_wifi.hoymiles
from hoymiles_wifi.hoymiles import BMSWorkingMode, DTUType, get_dtu_model_type

from .const import (
    CONF_DTU_SERIAL_NUMBER,
    CONF_HYBRID_INVERTERS,
    CONF_INVERTERS,
    CONF_METERS,
    CONF_OFFLINE_FALLBACK,
    CONF_PORTS,
    CONF_THREE_PHASE_INVERTERS,
    DOMAIN,
    FCTN_GENERATE_DTU_VERSION_STRING,
    FCTN_GENERATE_INVERTER_HW_VERSION_STRING,
    FCTN_GENERATE_INVERTER_SW_VERSION_STRING,
    HASS_APP_INFO_COORDINATOR,
    HASS_CONFIG_COORDINATOR,
    HASS_DATA_COORDINATOR,
    HASS_ENERGY_STORAGE_CONFIG_COORDINATOR,
    HASS_ENERGY_STORAGE_DATA_COORDINATOR,
)
from .entity import DeviceType, HoymilesCoordinatorEntity, HoymilesEntityDescription

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
    version_translation_function: str = None
    version_prefix: str = None
    requires_device_type: int = DeviceType.ALL_DEVICES
    is_daily_energy: bool = False


@dataclass(frozen=True)
class HoymilesEnergyStorageSensorEntityDescription(
    HoymilesEntityDescription, SensorEntityDescription
):
    """Describes Hoymiles energy storage data sensor entity."""

    model_name: str = None
    conversion_factor: float = None
    version_translation_function: str = None
    version_prefix: str = None


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
        is_daily_energy=True,
        translation_key="ac_daily_energy",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
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
        key="tgs_data[<inverter_count>].current_phase_A",
        translation_key="current_phase_A",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.01,
    ),
    HoymilesSensorEntityDescription(
        key="tgs_data[<inverter_count>].current_phase_B",
        translation_key="current_phase_B",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.01,
    ),
    HoymilesSensorEntityDescription(
        key="tgs_data[<inverter_count>].current_phase_C",
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
        is_daily_energy=True,
        translation_key="port_dc_daily_energy",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
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
    ),
    HoymilesSensorEntityDescription(
        key="dtu_info.dtu_hw_version",
        translation_key="dtu_hw_version",
        entity_category=EntityCategory.DIAGNOSTIC,
        version_translation_function=FCTN_GENERATE_DTU_VERSION_STRING,
        version_prefix="H",
        is_dtu_sensor=True,
    ),
    HoymilesSensorEntityDescription(
        key="pv_info[<inverter_count>].pv_sw_version",
        translation_key="pv_sw_version",
        entity_category=EntityCategory.DIAGNOSTIC,
        version_translation_function=FCTN_GENERATE_INVERTER_SW_VERSION_STRING,
        version_prefix="V",
    ),
    HoymilesSensorEntityDescription(
        key="pv_info[<inverter_count>].pv_hw_version",
        translation_key="pv_hw_version",
        entity_category=EntityCategory.DIAGNOSTIC,
        version_translation_function=FCTN_GENERATE_INVERTER_HW_VERSION_STRING,
        version_prefix="H",
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
        conversion_factor=0.01,
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
        conversion_factor=0.01,
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
            class_name = (
                HoymilesEnergySensorEntity
                if description.device_class == SensorDeviceClass.ENERGY
                else HoymilesDataSensorEntity
            )

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
        sensors.extend(
            get_sensors_for_hybrid_inverter_description(
                config_entry,
                HoymilesEnergyStorageSensorEntityDescription(
                    key="[<inverter_count>].emspara",
                    translation_key="working_mode",
                    device_class=SensorDeviceClass.ENUM,
                    options=[
                        mode.name.lower()
                        for mode in BMSWorkingMode
                        if mode != BMSWorkingMode.UNKNOWN
                    ],
                ),
                hass_data[HASS_ENERGY_STORAGE_CONFIG_COORDINATOR],
                HoymilesWorkingModeSensorEntity,
                dtu_serial_number,
                hybrid_inverters,
            )
        )
        for description in HOYMILES_ENERGY_STORAGE_SENSORS:
            sensor_entities = get_sensors_for_hybrid_inverter_description(
                config_entry,
                description,
                energy_storage_data_coordinator,
                HoymilesEnergySensorEntity
                if description.device_class == SensorDeviceClass.ENERGY
                else HoymilesEnergyStorageSensorEntity,
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
    meters: list | None = None,
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
        for index, meter in enumerate(meters or ()):
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
                _LOGGER.error("Error getting DTU model type: %s", e)

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
                for pv_index in range(2):
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
                for phase_index in range(3):
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


class HoymilesDataSensorEntity(HoymilesCoordinatorEntity, SensorEntity):
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
        self._last_energy_value = None
        self._last_energy_date = None

        self.update_state_value()

    async def async_added_to_hass(self) -> None:
        """Schedule midnight updates only for optional daily-energy fallback."""
        await super().async_added_to_hass()
        if self._config_entry.data.get(CONF_OFFLINE_FALLBACK, False) and getattr(
            self.entity_description, "is_daily_energy", False
        ):
            self.async_on_remove(
                async_track_time_change(
                    self.hass,
                    self._async_refresh_daily_fallback,
                    hour=0,
                    minute=0,
                    second=0,
                )
            )

    @callback
    def _async_refresh_daily_fallback(self, now) -> None:
        """Re-evaluate an offline daily total at local midnight."""
        self.async_write_ha_state()

    def _uses_offline_fallback(self) -> bool:
        """Use offline estimates after grace, with daily rollover at local midnight."""
        return (
            self._config_entry.data.get(CONF_OFFLINE_FALLBACK, False)
            and self.coordinator.get_dtu().get_state() == NetworkState.Offline
            and (
                not self.coordinator.last_update_success
                or (self.coordinator.data_is_stale and self._daily_total_has_expired())
            )
        )

    def _daily_total_has_expired(self) -> bool:
        """Detect a retained daily counter from an earlier local calendar day."""
        return (
            getattr(self.entity_description, "is_daily_energy", False)
            and self._last_energy_date is not None
            and self._last_energy_date < dt_util.now().date()
        )

    def _offline_fallback_value(self):
        """Retain known energy totals and estimate instantaneous measurements as zero."""
        if self.device_class == SensorDeviceClass.ENERGY:
            if self._daily_total_has_expired() or self._last_energy_value is None:
                return 0
            return self._last_energy_value
        if self.state_class == SensorStateClass.MEASUREMENT:
            return 0
        return None

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.update_state_value()
        super()._handle_coordinator_update()

    @property
    def native_value(self):
        """Return the native value of the sensor."""
        if self._uses_offline_fallback():
            return self._offline_fallback_value()
        return self._native_value

    @property
    def assumed_state(self):
        """Return the assumed state of the sensor."""
        return (
            getattr(self.coordinator, "data_is_stale", False)
            or self._uses_offline_fallback()
        )

    @property
    def available(self) -> bool:
        """Expose a state only when the coordinator and this reading are available."""
        if self._uses_offline_fallback():
            return self._offline_fallback_value() is not None
        return super().available and self._native_value is not None

    def _read_coordinator_value(self):
        """Resolve this sensor's attribute path, returning None for missing data."""
        value = getattr(self.coordinator, "data", None)
        for token in re.findall(r"\w+|\[\d+\]", self._attribute_name):
            if value is None:
                return None
            if token.startswith("["):
                try:
                    value = value[int(token[1:-1])]
                except (IndexError, TypeError):
                    return None
            else:
                value = getattr(value, token, None)
        return value

    def update_state_value(self):
        """Update measurements and counters only from fresh coordinator data."""
        if getattr(self.coordinator, "data_is_stale", False):
            return

        new_native_value = self._read_coordinator_value()

        if new_native_value is not None and self._conversion_factor is not None:
            new_native_value *= self._conversion_factor

        if (
            new_native_value is not None
            and self._version_translation_function is not None
        ):
            new_native_value = getattr(
                hoymiles_wifi.hoymiles, self._version_translation_function
            )(int(new_native_value))

        if new_native_value is not None and self._version_prefix is not None:
            new_native_value = f"{self._version_prefix}{new_native_value}"

        self._native_value = new_native_value
        if (
            self.device_class == SensorDeviceClass.ENERGY
            and new_native_value is not None
        ):
            self._last_energy_value = new_native_value
            self._last_energy_date = dt_util.now().date()


class HoymilesEnergySensorEntity(HoymilesDataSensorEntity, RestoreSensor):
    """Restore lifetime counters and suppress zeros that would reset statistics."""

    def __init__(self, config_entry, description, coordinator):
        """Initialize zero-reading protection before the first coordinator value."""
        self._filtered_zero = False
        super().__init__(config_entry, description, coordinator)

    @property
    def _is_daily_energy(self) -> bool:
        """Identify counters for which a reset to zero is a normal daily event."""
        return getattr(self.entity_description, "is_daily_energy", False)

    def update_state_value(self):
        """Keep zero lifetime readings out of the sensor and its stored counter."""
        if getattr(self.coordinator, "data_is_stale", False):
            return
        self._filtered_zero = (
            not self._is_daily_energy and self._read_coordinator_value() == 0
        )
        if self._filtered_zero:
            _LOGGER.debug(
                "Ignoring zero lifetime energy reading for %s",
                self.entity_description.key,
            )
            self._native_value = self._last_energy_value
            return
        super().update_state_value()

    async def async_added_to_hass(self) -> None:
        """Restore a known lifetime total unless fresh data has already supplied it."""
        await super().async_added_to_hass()
        if self._is_daily_energy or self._last_energy_value is not None:
            return
        restored = await self.async_get_last_sensor_data()
        if (
            restored is not None
            and restored.native_unit_of_measurement == self.native_unit_of_measurement
            and isinstance(restored.native_value, (int, float))
            and restored.native_value > 0
        ):
            self._last_energy_value = restored.native_value
            if self._filtered_zero:
                self._native_value = restored.native_value

    @property
    def extra_restore_state_data(self):
        """Persist only reported lifetime totals, including while unavailable."""
        if self._is_daily_energy:
            return None
        return SensorExtraStoredData(
            self._last_energy_value, self.native_unit_of_measurement
        )

    @property
    def assumed_state(self):
        """Identify values retained instead of a zero lifetime reading."""
        return super().assumed_state or self._filtered_zero

    def _offline_fallback_value(self):
        """Never fabricate a zero lifetime counter when no prior total is known."""
        if not self._is_daily_energy and self._last_energy_value is None:
            return None
        return super()._offline_fallback_value()


class HoymilesDiagnosticSensorEntity(HoymilesCoordinatorEntity, SensorEntity):
    """Represents a diagnostic sensor entity for Hoymiles data."""

    def __init__(self, config_entry, description, coordinator):
        """Initialize the HoymilesSensorEntity."""
        super().__init__(config_entry, description, coordinator)

        self._attribute_name = description.key
        self._conversion = description.conversion
        self._separator = description.separator
        self._native_value = None

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
    def available(self) -> bool:
        """Expose a state only when the coordinator and this reading are available."""
        return super().available and self._native_value is not None

    @property
    def assumed_state(self) -> bool:
        """Mark cached diagnostic readings during the shared outage grace period."""
        return getattr(self.coordinator, "data_is_stale", False)

    def update_state_value(self):
        """Update the state value of the sensor."""
        if getattr(self.coordinator, "data_is_stale", False):
            return

        if "[" in self._attribute_name and "]" in self._attribute_name:
            attribute_parts = self._attribute_name.split("[")
            attribute_name = attribute_parts[0]
            index_range = attribute_parts[1].split("]")[0]
            start, end = map(int, index_range.split("-"))

            new_attribute_names = [
                f"{attribute_name}{i}" for i in range(start, end + 1)
            ]
            attribute_values = [
                getattr(self.coordinator.data, attr, None)
                for attr in new_attribute_names
            ]

            if any(value is None or value == "" for value in attribute_values):
                self._native_value = None
            else:
                self._native_value = self._separator.join(map(str, attribute_values))
        else:
            self._native_value = getattr(
                self.coordinator.data, self._attribute_name, None
            )

        if self._native_value is not None and self._conversion == ConversionAction.HEX:
            self._native_value = self._separator.join(
                hex(int(value))[2:]
                for value in self._native_value.split(self._separator)
            ).upper()


class HoymilesEnergyStorageSensorEntity(HoymilesDataSensorEntity):
    """Use the shared live-data sensor handling for hybrid inverters."""


class HoymilesWorkingModeSensorEntity(HoymilesEnergyStorageSensorEntity):
    """Expose the reported working mode and its unmodified EMS settings."""

    def _read_coordinator_value(self):
        """Treat absent EMS settings as a missing reading, rather than mode zero."""
        settings = super()._read_coordinator_value()
        return settings if settings is not None and settings.ListFields() else None

    @property
    def native_value(self) -> str | None:
        """Translate a recognized protocol mode to its stable enum state."""
        if self._native_value is None:
            return None
        try:
            mode = BMSWorkingMode(self._native_value.mode)
        except ValueError:
            return None
        return mode.name.lower() if mode != BMSWorkingMode.UNKNOWN else None

    @property
    def extra_state_attributes(self):
        """Include reported settings with protocol field names and raw units."""
        if self._native_value is None:
            return None
        return {
            "settings": MessageToDict(
                self._native_value,
                preserving_proto_field_name=True,
                always_print_fields_with_no_presence=True,
            )
        }
