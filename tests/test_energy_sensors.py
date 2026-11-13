"""Protect lifetime statistics against zero and omitted protobuf counters."""

from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorExtraStoredData,
    SensorStateClass,
)
from homeassistant.const import UnitOfEnergy
from hoymiles_wifi.dtu import NetworkState
from hoymiles_wifi.protobuf import ESData_pb2, RealDataNew_pb2
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hoymiles_wifi.const import (
    CONF_DTU_SERIAL_NUMBER,
    CONF_HYBRID_INVERTERS,
    CONF_INVERTERS,
    CONF_OFFLINE_FALLBACK,
    CONF_PORTS,
    DOMAIN,
    HASS_APP_INFO_COORDINATOR,
    HASS_CONFIG_COORDINATOR,
    HASS_DATA_COORDINATOR,
    HASS_ENERGY_STORAGE_CONFIG_COORDINATOR,
    HASS_ENERGY_STORAGE_DATA_COORDINATOR,
)
from custom_components.hoymiles_wifi.coordinator import (
    HoymilesRealDataUpdateCoordinator,
)
from custom_components.hoymiles_wifi.sensor import (
    HoymilesEnergySensorEntity,
    HoymilesSensorEntityDescription,
    async_setup_entry,
)

DTU_SERIAL = "4143A6B7C8D9"
INVERTER_SERIAL = "1123A6B7C8D9"


def response(counter=None, *, explicit_zero=False):
    """Create a real protobuf with a counter, an omitted field, or a wire-level zero."""
    result = RealDataNew_pb2.RealDataNewReqDTO(device_serial_number=DTU_SERIAL)
    if explicit_zero:
        result.pv_data.add().ParseFromString(bytes.fromhex("080110013000"))
    else:
        port = result.pv_data.add(serial_number=1, port_number=1)
        if counter is not None:
            port.energy_total = counter
    return result


@pytest.fixture
async def energy_sensor(hass):
    """Exercise production sensor classes against actual protobuf responses."""
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_DTU_SERIAL_NUMBER: DTU_SERIAL})
    entry.add_to_hass(hass)
    dtu = SimpleNamespace(get_state=lambda: NetworkState.Offline)
    coordinator = HoymilesRealDataUpdateCoordinator(
        hass, dtu, entry, timedelta(seconds=35)
    )
    description = HoymilesSensorEntityDescription(
        key="pv_data[0].energy_total",
        serial_number=DTU_SERIAL,
        is_dtu_sensor=True,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
    )
    sensors = []

    def create(**changes):
        sensor = HoymilesEnergySensorEntity(
            entry, replace(description, **changes), coordinator
        )
        sensor.hass = hass
        sensor.entity_id = f"sensor.test_energy_{len(sensors)}"
        sensors.append(sensor)
        return sensor

    yield entry, coordinator, create
    for sensor in sensors:
        if sensor._on_remove:
            await sensor.async_remove(force_remove=True)
    await coordinator.async_shutdown()


@pytest.mark.parametrize(
    "explicit_zero", [False, True], ids=["omitted", "explicit-zero"]
)
@pytest.mark.parametrize("conversion_factor", [None, 0.1])
async def test_lifetime_counter_does_not_publish_transient_zero(
    energy_sensor, explicit_zero, conversion_factor
):
    """A decoded zero must neither reset the counter nor scale the cached value twice."""
    _, coordinator, create = energy_sensor
    sensor = create(conversion_factor=conversion_factor)
    expected = 847958 * (conversion_factor if conversion_factor is not None else 1)
    for reading, assumed in (
        (response(847958), False),
        (response(explicit_zero=explicit_zero), True),
        (response(847958), False),
    ):
        coordinator.async_set_updated_data(reading)
        sensor.update_state_value()
        assert sensor.native_value == expected
        assert sensor.available
        assert sensor.assumed_state is assumed
        assert sensor.extra_restore_state_data.native_value == expected
        sensor.async_write_ha_state()
        assert float(sensor.hass.states.get(sensor.entity_id).state) == expected


@pytest.mark.parametrize("offline_fallback", [False, True])
async def test_first_zero_lifetime_counter_is_unavailable(
    hass, energy_sensor, offline_fallback
):
    """Even the optional offline setting must not invent an unknown lifetime total."""
    entry, coordinator, create = energy_sensor
    hass.config_entries.async_update_entry(
        entry, data={**entry.data, CONF_OFFLINE_FALLBACK: offline_fallback}
    )
    coordinator.async_set_updated_data(response())
    sensor = create()
    assert sensor.native_value is None
    assert not sensor.available
    coordinator.last_update_success = False
    coordinator.data_is_stale = True
    assert sensor.native_value is None
    assert not sensor.available


@pytest.mark.parametrize("unit", ["Wh", "kWh"])
@pytest.mark.parametrize("stored_value", [847958, 0, None])
async def test_restore_known_lifetime_total_and_preserve_it_while_unavailable(
    energy_sensor, unit, stored_value
):
    """Restore native units and retain the real counter even when current data is missing."""
    _, coordinator, create = energy_sensor
    coordinator.async_set_updated_data(response())
    sensor = create()
    with patch.object(
        sensor,
        "async_get_last_extra_data",
        new=AsyncMock(return_value=SensorExtraStoredData(stored_value, unit)),
    ):
        sensor.platform = SimpleNamespace(platform_name=DOMAIN, config_entry=None)
        await sensor.add_to_platform_finish()
    valid = unit == "Wh" and stored_value == 847958
    assert sensor.available is valid
    if valid:
        assert sensor.native_value == 847958
        assert sensor.assumed_state
        coordinator.async_set_updated_data(
            RealDataNew_pb2.RealDataNewReqDTO(device_serial_number=DTU_SERIAL)
        )
        sensor.update_state_value()
        assert not sensor.available
        assert sensor.extra_restore_state_data.native_value == 847958


async def test_fresh_counter_takes_precedence_over_restore_data(energy_sensor):
    """Never replace an already received reading with historical storage."""
    _, coordinator, create = energy_sensor
    coordinator.async_set_updated_data(response(900000))
    sensor = create()
    with patch.object(
        sensor, "async_get_last_extra_data", new_callable=AsyncMock
    ) as restore:
        sensor.platform = SimpleNamespace(platform_name=DOMAIN, config_entry=None)
        await sensor.add_to_platform_finish()
    restore.assert_not_awaited()
    assert sensor.native_value == 900000
    assert not sensor.assumed_state


async def test_daily_counter_accepts_zero_and_is_not_restored(energy_sensor):
    """Daily resets remain valid and daily counters retain their in-memory behavior."""
    _, coordinator, create = energy_sensor
    coordinator.async_set_updated_data(response())
    sensor = create(key="pv_data[0].energy_daily", is_daily_energy=True)
    with patch.object(
        sensor, "async_get_last_extra_data", new_callable=AsyncMock
    ) as restore:
        sensor.platform = SimpleNamespace(platform_name=DOMAIN, config_entry=None)
        await sensor.add_to_platform_finish()
    restore.assert_not_awaited()
    assert sensor.native_value == 0
    assert sensor.available
    assert not sensor.assumed_state
    assert sensor.extra_restore_state_data is None


@pytest.mark.parametrize("hybrid", [False, True])
async def test_sensor_platform_uses_energy_class(hass, energy_sensor, hybrid):
    """Wire regular, port, and hybrid energy descriptions to the restored energy class."""
    entry, coordinator, _ = energy_sensor
    hass.config_entries.async_update_entry(
        entry,
        data={
            **entry.data,
            CONF_INVERTERS: [] if hybrid else [INVERTER_SERIAL],
            CONF_PORTS: []
            if hybrid
            else [{"inverter_serial_number": INVERTER_SERIAL, "port_number": 1}],
            CONF_HYBRID_INVERTERS: [
                {
                    "inverter_serial_number": "1234567800000002",
                    "model_name": "HYT-5.0HV-EUG1",
                }
            ]
            if hybrid
            else [],
        },
    )
    coordinator.async_set_updated_data(
        [ESData_pb2.ESDataReqDTO()] if hybrid else response(847958)
    )
    hass.data[DOMAIN] = {
        entry.entry_id: {
            key: coordinator
            for key in (
                HASS_DATA_COORDINATOR,
                HASS_CONFIG_COORDINATOR,
                HASS_APP_INFO_COORDINATOR,
                HASS_ENERGY_STORAGE_DATA_COORDINATOR,
                HASS_ENERGY_STORAGE_CONFIG_COORDINATOR,
            )
        }
    }
    sensors = []
    await async_setup_entry(hass, entry, sensors.extend)
    energy = [
        sensor for sensor in sensors if sensor.device_class == SensorDeviceClass.ENERGY
    ]
    assert energy
    assert all(isinstance(sensor, HoymilesEnergySensorEntity) for sensor in energy)
    assert any(not isinstance(sensor, HoymilesEnergySensorEntity) for sensor in sensors)


@pytest.mark.parametrize("offline_fallback", [False, True])
async def test_restore_while_offline_keeps_coordinator_availability(
    hass, energy_sensor, offline_fallback
):
    """Restore the counter without masking offline status unless the user opts in."""
    entry, coordinator, create = energy_sensor
    hass.config_entries.async_update_entry(
        entry, data={**entry.data, CONF_OFFLINE_FALLBACK: offline_fallback}
    )
    coordinator.last_update_success = False
    coordinator.data_is_stale = True
    sensor = create()
    with patch.object(
        sensor,
        "async_get_last_extra_data",
        new=AsyncMock(return_value=SensorExtraStoredData(847958, "Wh")),
    ):
        sensor.platform = SimpleNamespace(platform_name=DOMAIN, config_entry=None)
        await sensor.add_to_platform_finish()
    assert sensor.available is offline_fallback
    assert sensor.extra_restore_state_data.native_value == 847958
    if offline_fallback:
        assert sensor.native_value == 847958
        assert sensor.assumed_state
