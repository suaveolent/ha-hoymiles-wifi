"""Tests for the operating status and alarm in each port's error code."""

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hoymiles_wifi.const import CONF_DTU_SERIAL_NUMBER, DOMAIN
from custom_components.hoymiles_wifi.coordinator import (
    HoymilesRealDataUpdateCoordinator,
)
from custom_components.hoymiles_wifi.sensor import (
    HOYMILES_SENSORS,
    HoymilesDataSensorEntity,
    get_sensors_for_description,
)

PORT_KEYS = ("port_error_code", "port_operating_status", "port_alarm_code")


@pytest.fixture
def port_sensors(hass):
    """Create a port's error code sensors on a real coordinator."""
    entry = MockConfigEntry(
        domain=DOMAIN, data={CONF_DTU_SERIAL_NUMBER: "4143A01B0514"}
    )
    entry.add_to_hass(hass)
    dtu = SimpleNamespace(async_get_real_data_new=AsyncMock())
    coordinator = HoymilesRealDataUpdateCoordinator(
        hass=hass,
        dtu=dtu,
        config_entry=entry,
        update_interval=timedelta(seconds=35),
    )
    ports = [{"inverter_serial_number": "112345678901", "port_number": 1}]
    sensors = {}
    for description in HOYMILES_SENSORS:
        if description.translation_key in PORT_KEYS:
            (sensor,) = get_sensors_for_description(
                entry,
                description,
                coordinator,
                HoymilesDataSensorEntity,
                "4143A01B0514",
                [],
                ports,
            )
            sensors[description.translation_key] = sensor
    return coordinator, dtu.async_get_real_data_new, sensors


@pytest.mark.parametrize(
    ("raw", "status", "alarm"),
    [
        (0, 0, 0),
        (0x03000000, 3, 0),
        (0x03090000, 3, 0x090000),
        (0x00000001, 0, 1),
        # protobuf int32: a set top bit arrives negative.
        (-0x01000000, 0xFF, 0),
    ],
)
async def test_status_and_alarm(port_sensors, raw, status, alarm):
    """The top byte is the operating status and the rest the alarm."""
    coordinator, fetch, sensors = port_sensors
    fetch.return_value = SimpleNamespace(pv_data=[SimpleNamespace(error_code=raw)])
    await coordinator.async_refresh()
    for sensor in sensors.values():
        sensor.update_state_value()
    assert sensors["port_error_code"].native_value == raw
    assert sensors["port_operating_status"].native_value == status
    assert sensors["port_alarm_code"].native_value == alarm
    await coordinator.async_shutdown()


async def test_missing_port(port_sensors):
    """A port missing from the response leaves all three unavailable."""
    coordinator, fetch, sensors = port_sensors
    fetch.return_value = SimpleNamespace(pv_data=[])
    await coordinator.async_refresh()
    for sensor in sensors.values():
        sensor.update_state_value()
        assert sensor.native_value is None
        assert not sensor.available
    await coordinator.async_shutdown()


def test_unique_ids(port_sensors):
    """Each of the three sensors gets its own unique ID."""
    _, _, sensors = port_sensors
    assert len({sensor.unique_id for sensor in sensors.values()}) == 3
