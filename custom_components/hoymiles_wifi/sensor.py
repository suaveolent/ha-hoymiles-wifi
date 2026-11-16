"""Support for Hoymiles sensors."""

import dataclasses
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
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_change
from homeassistant.util import dt as dt_util
from hoymiles_wifi.dtu import NetworkState
import hoymiles_wifi.hoymiles
from hoymiles_wifi.hoymiles import BMSWorkingMode, DTUType

from .const import (
    CONF_DTU_SERIAL_NUMBER,
    CONF_HYBRID_INVERTERS,
    CONF_INVERTERS,
    CONF_METERS,
    CONF_OFFLINE_FALLBACK,
    CONF_PORTS,
    CONF_THREE_PHASE_INVERTERS,
    DOMAIN,
    HASS_APP_INFO_COORDINATOR,
    HASS_CONFIG_COORDINATOR,
    HASS_DATA_COORDINATOR,
    HASS_ENERGY_STORAGE_CONFIG_COORDINATOR,
    HASS_ENERGY_STORAGE_DATA_COORDINATOR,
)
from .entity import DeviceType, HoymilesCoordinatorEntity
from .sensor_descriptions import (
    APP_INFO_SENSORS,
    CONFIG_DIAGNOSTIC_SENSORS,
    HOYMILES_ENERGY_STORAGE_SENSORS,
    HOYMILES_SENSORS,
    ConversionAction,
    HoymilesEnergyStorageSensorEntityDescription,
    HoymilesSensorEntityDescription,
)
from .util import get_dtu_type

_LOGGER = logging.getLogger(__name__)


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
        dtu_type = get_dtu_type(dtu_serial_number)

        if (
            description.supported_dtu_types is None
            or dtu_type == DTUType.UNKNOWN
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
        """Schedule one local midnight callback for daily-energy sensors."""
        await super().async_added_to_hass()
        if getattr(self.entity_description, "reset_at_midnight", False):
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
            getattr(self.entity_description, "reset_at_midnight", False)
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
    """Restore energy counters and protect totals from invalid decreases."""

    def __init__(self, config_entry, description, coordinator):
        """Initialize zero-reading protection before the first coordinator value."""
        self._filtered_reading = False
        super().__init__(config_entry, description, coordinator)

    @property
    def _resets_at_midnight(self) -> bool:
        """Identify counters configured to reset their cached value at midnight."""
        return getattr(self.entity_description, "reset_at_midnight", False)

    def _should_retain_energy_value(self, value) -> bool:
        """Filter zeros and configured same-day decreases without hiding missing data."""
        if value is None:
            return False
        if value == 0:
            return True
        if (
            not getattr(self.entity_description, "force_keep_maximum_within_day", False)
            or self._last_energy_value is None
            or self._last_energy_date != dt_util.now().date()
        ):
            return False
        if self._conversion_factor is not None:
            value *= self._conversion_factor
        return value < self._last_energy_value

    def update_state_value(self):
        """Retain protected counters while preserving coordinator outage handling."""
        if getattr(self.coordinator, "data_is_stale", False):
            return
        if self._daily_total_has_expired():
            self._reset_daily_energy()
        value = self._read_coordinator_value()
        self._filtered_reading = self._should_retain_energy_value(value)
        if self._filtered_reading:
            _LOGGER.debug(
                "Retaining energy total %s instead of %s for %s",
                self._last_energy_value,
                value,
                self.entity_description.key,
            )
            self._native_value = self._last_energy_value
            return
        super().update_state_value()

    def _reset_daily_energy(self) -> None:
        """Start a new daily fallback without changing lifetime totals."""
        if self._last_energy_value is None:
            return
        self._last_energy_value = 0
        self._last_energy_date = dt_util.now().date()
        if self._native_value is not None:
            self._native_value = 0
            self._filtered_reading = True
        _LOGGER.debug(
            "Resetting daily energy fallback for %s", self.entity_description.key
        )

    @callback
    def _async_refresh_daily_fallback(self, now) -> None:
        """Reset the daily fallback at midnight and preserve offline availability."""
        self._reset_daily_energy()
        super()._async_refresh_daily_fallback(now)

    async def async_added_to_hass(self) -> None:
        """Restore known counters before a startup zero can become a false reset."""
        await super().async_added_to_hass()
        if self._last_energy_value is not None:
            return
        restored = await self.async_get_last_sensor_data()
        if (
            restored is None
            or restored.native_unit_of_measurement != self.native_unit_of_measurement
            or not isinstance(restored.native_value, (int, float))
            or restored.native_value < 0
        ):
            return
        if restored.native_value == 0 and not self._resets_at_midnight:
            return
        self._last_energy_value = restored.native_value
        self._last_energy_date = dt_util.now().date()
        if self._filtered_reading:
            self._native_value = restored.native_value

    @property
    def extra_restore_state_data(self):
        """Persist the last accepted counter even while the entity is unavailable."""
        return SensorExtraStoredData(
            self._last_energy_value, self.native_unit_of_measurement
        )

    @property
    def assumed_state(self):
        """Identify retained counters and midnight fallback values."""
        return super().assumed_state or self._filtered_reading

    def _offline_fallback_value(self):
        """Never fabricate a counter reset when no prior total is known."""
        if self._last_energy_value is None:
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
