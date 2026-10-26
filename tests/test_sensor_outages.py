"""Regression tests for brief outages and missing live measurements."""

from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hoymiles_wifi.const import CONF_DTU_SERIAL_NUMBER, DOMAIN
from custom_components.hoymiles_wifi.coordinator import (
    HoymilesAppInfoUpdateCoordinator,
    HoymilesConfigUpdateCoordinator,
    HoymilesEnergyStorageUpdateCoordinator,
    HoymilesRealDataUpdateCoordinator,
)
from custom_components.hoymiles_wifi.sensor import (
    APP_INFO_SENSORS,
    HOYMILES_SENSORS,
    HoymilesDataSensorEntity,
    HoymilesDiagnosticEntityDescription,
    HoymilesDiagnosticSensorEntity,
    HoymilesEnergyStorageSensorEntity,
    HoymilesSensorEntityDescription,
)


@pytest.fixture(params=[False, True], ids=["regular", "hybrid"])
def live_sensor(hass, request):
    """Create real coordinators and sensors with only the DTU transport mocked."""
    hybrid = request.param
    entry = MockConfigEntry(
        domain=DOMAIN, data={CONF_DTU_SERIAL_NUMBER: "4143A01B0514"}
    )
    entry.add_to_hass(hass)
    dtu = SimpleNamespace(
        async_get_real_data_new=AsyncMock(),
        async_get_energy_storage_data=AsyncMock(),
    )
    kwargs = {
        "hass": hass,
        "dtu": dtu,
        "config_entry": entry,
        "update_interval": timedelta(seconds=35),
    }
    if hybrid:
        coordinator = HoymilesEnergyStorageUpdateCoordinator(
            **kwargs, dtu_serial_number=123, inverters=[{"inverter_serial_number": 456}]
        )
        fetch = dtu.async_get_energy_storage_data
        sensor_class = HoymilesEnergyStorageSensorEntity
    else:
        coordinator = HoymilesRealDataUpdateCoordinator(**kwargs)
        fetch = dtu.async_get_real_data_new
        sensor_class = HoymilesDataSensorEntity
    description = HoymilesSensorEntityDescription(
        key="[0].power" if hybrid else "power",
        serial_number="4143A01B0514",
        is_dtu_sensor=True,
        conversion_factor=0.1,
    )
    sensor = sensor_class(entry, description, coordinator)
    sensor.hass = hass
    sensor.entity_id = "sensor.test_power"
    return coordinator, fetch, sensor


@pytest.mark.parametrize("failure", [None, TimeoutError(), OSError("disconnected")])
async def test_outage_grace_and_recovery(hass, live_sensor, failure):
    """Short outages retain readings, long ones become unavailable, zero is valid."""
    coordinator, fetch, sensor = live_sensor
    remove_listener = coordinator.async_add_listener(sensor._handle_coordinator_update)

    async def refresh():
        await coordinator.async_refresh()
        return hass.states.get(sensor.entity_id)

    with patch(
        "custom_components.hoymiles_wifi.coordinator.monotonic", return_value=0
    ) as clock:
        fetch.return_value = SimpleNamespace(power=250)
        assert (await refresh()).state == "25.0"
        assert not sensor.assumed_state

        fetch.side_effect = failure if isinstance(failure, Exception) else None
        fetch.return_value = None
        for now in (35, 70, 179):
            clock.return_value = now
            state = await refresh()
            assert state.state == "25.0"
            assert state.attributes["assumed_state"] is True
            # Reading the property repeatedly must not extend the grace period.
            assert sensor.native_value == sensor.native_value == 25.0

        clock.return_value = 180
        assert (await refresh()).state == "unavailable"
        clock.return_value = 215
        assert (await refresh()).state == "unavailable"

        clock.return_value = 250
        fetch.side_effect = None
        fetch.return_value = SimpleNamespace(power=0)
        assert (await refresh()).state == "0.0"
        assert not sensor.assumed_state

        fetch.return_value = SimpleNamespace()
        assert (await refresh()).state == "unavailable"
        assert not sensor.available

        remove_listener()
        await coordinator.async_shutdown()


async def test_repeated_short_outages(hass, live_sensor):
    """A successful zero reading starts a fresh grace period for the next outage."""
    coordinator, fetch, sensor = live_sensor
    remove_listener = coordinator.async_add_listener(sensor._handle_coordinator_update)

    with patch("custom_components.hoymiles_wifi.coordinator.monotonic") as clock:
        for now, power, expected in (
            (0, 250, "25.0"),
            (35, None, "25.0"),
            (70, 0, "0.0"),
            (220, None, "0.0"),
            (250, None, "unavailable"),
            (285, 300, "30.0"),
        ):
            clock.return_value = now
            fetch.return_value = None if power is None else SimpleNamespace(power=power)
            await coordinator.async_refresh()
            assert hass.states.get(sensor.entity_id).state == expected
            assert sensor.assumed_state is (power is None)

    remove_listener()
    await coordinator.async_shutdown()


async def test_no_grace_without_success(live_sensor):
    """There is no fabricated reading when the first request fails."""
    coordinator, fetch, sensor = live_sensor
    fetch.return_value = None
    await coordinator.async_refresh()
    sensor.update_state_value()
    assert not sensor.available
    assert sensor.native_value is None
    await coordinator.async_shutdown()


async def test_partial_hybrid_response_preserves_indexes(hass):
    """A missing first inverter must not shift another inverter's measurements."""
    entry = MockConfigEntry(domain=DOMAIN)
    entry.add_to_hass(hass)
    second = SimpleNamespace(power=123)
    dtu = SimpleNamespace(
        async_get_energy_storage_data=AsyncMock(side_effect=[None, second])
    )
    coordinator = HoymilesEnergyStorageUpdateCoordinator(
        hass,
        dtu,
        entry,
        timedelta(seconds=35),
        123,
        [{"inverter_serial_number": 1}, {"inverter_serial_number": 2}],
    )
    await coordinator.async_refresh()
    assert coordinator.data == [None, second]
    assert coordinator.last_update_success
    assert not coordinator.data_is_stale
    await coordinator.async_shutdown()


async def test_counter_reports_decreases_and_missing_values(live_sensor):
    """Valid counter decreases are exposed and missing readings are unavailable."""
    coordinator, fetch, original = live_sensor
    sensor = type(original)(
        original._config_entry,
        HoymilesSensorEntityDescription(
            key=original.entity_description.key,
            serial_number="4143A01B0514",
            is_dtu_sensor=True,
        ),
        coordinator,
    )
    for raw, expected in [(100, 100), (None, None), (90, 90), (110, 110)]:
        fetch.return_value = SimpleNamespace(power=raw)
        await coordinator.async_refresh()
        sensor.update_state_value()
        assert sensor.native_value == expected
    fetch.return_value = SimpleNamespace(power=5)
    await coordinator.async_refresh()
    sensor.update_state_value()
    assert sensor.native_value == 5
    await coordinator.async_shutdown()


async def test_energy_counter_accepts_zero(live_sensor):
    """A successful zero reading is not replaced with a previous counter value."""
    coordinator, fetch, original = live_sensor
    sensor = HoymilesDataSensorEntity(
        original._config_entry,
        original.entity_description,
        coordinator,
    )
    for raw, expected in [(100, 10.0), (None, None), (0, 0.0), (120, 12.0)]:
        fetch.return_value = SimpleNamespace(power=raw)
        await coordinator.async_refresh()
        sensor.update_state_value()
        assert sensor.native_value == expected
    await coordinator.async_shutdown()


@pytest.mark.parametrize(
    "description",
    [
        description
        for description in HOYMILES_SENSORS
        if description.translation_key in ("ac_daily_energy", "port_dc_daily_energy")
    ],
    ids=lambda description: description.translation_key,
)
async def test_daily_energy_accepts_zero_and_preserves_outage_handling(
    live_sensor, description
):
    """Device resets are valid readings; missing and stale readings are not zeros."""
    coordinator, fetch, original = live_sensor
    sensor = HoymilesDataSensorEntity(
        original._config_entry,
        replace(
            description,
            key=original.entity_description.key,
            serial_number="4143A01B0514",
            is_dtu_sensor=True,
        ),
        coordinator,
    )
    for raw in [100, 0, 5, None, 0]:
        fetch.return_value = SimpleNamespace(power=raw)
        await coordinator.async_refresh()
        sensor.update_state_value()
        assert sensor.native_value == raw
        assert sensor.available == (raw is not None)
        assert not sensor.assumed_state

    fetch.return_value = None
    await coordinator.async_refresh()
    sensor.update_state_value()
    assert sensor.native_value == 0
    assert sensor.assumed_state

    coordinator._last_successful_fetch -= 181
    await coordinator.async_refresh()
    assert not sensor.available
    await coordinator.async_shutdown()


@pytest.mark.parametrize("description", APP_INFO_SENSORS[:4])
async def test_version_zero_is_formatted(live_sensor, description):
    """Firmware version zero is a valid value rather than an old restored version."""
    coordinator, fetch, original = live_sensor
    sensor = HoymilesDataSensorEntity(
        original._config_entry,
        replace(
            description,
            key=original.entity_description.key,
            is_dtu_sensor=True,
            serial_number="4143A01B0514",
        ),
        coordinator,
    )
    fetch.return_value = SimpleNamespace(power=0)
    await coordinator.async_refresh()
    sensor.update_state_value()
    assert sensor.available
    assert sensor.native_value.startswith(description.version_prefix)
    assert set(sensor.native_value[1:]) <= {"0", "."}
    assert not sensor.assumed_state
    await coordinator.async_shutdown()


@pytest.mark.parametrize(
    ("coordinator_type", "method"),
    [
        (HoymilesConfigUpdateCoordinator, "async_get_config"),
        (HoymilesAppInfoUpdateCoordinator, "async_app_information_data"),
    ],
)
async def test_diagnostic_zero_missing_and_outage(hass, coordinator_type, method):
    """Diagnostic readings share the live-data grace period without old-value fallbacks."""
    entry = MockConfigEntry(
        domain=DOMAIN, data={CONF_DTU_SERIAL_NUMBER: "4143A01B0514"}
    )
    entry.add_to_hass(hass)
    fetch = AsyncMock()
    dtu = SimpleNamespace(**{method: fetch})
    coordinator = coordinator_type(hass, dtu, entry, timedelta(seconds=300))
    sensor = HoymilesDiagnosticSensorEntity(
        entry,
        HoymilesDiagnosticEntityDescription(
            key="value_[0-1]",
            separator=".",
            is_dtu_sensor=True,
            serial_number="4143A01B0514",
        ),
        coordinator,
    )
    sensor.hass = hass
    sensor.entity_id = "sensor.test_diagnostic"
    remove_listener = coordinator.async_add_listener(sensor._handle_coordinator_update)
    with patch(
        "custom_components.hoymiles_wifi.coordinator.monotonic", return_value=0
    ) as clock:
        fetch.return_value = SimpleNamespace(
            value_0=1, value_1=2, dtu_info=SimpleNamespace(dfs=0)
        )
        await coordinator.async_refresh()
        assert hass.states.get(sensor.entity_id).state == "1.2"
        fetch.return_value = None
        clock.return_value = 100
        await coordinator.async_refresh()
        assert hass.states.get(sensor.entity_id).state == "1.2"
        assert sensor.assumed_state
        clock.return_value = 180
        await coordinator.async_refresh()
        assert hass.states.get(sensor.entity_id).state == "unavailable"
        fetch.return_value = SimpleNamespace(
            value_0=0, value_1=0, dtu_info=SimpleNamespace(dfs=0)
        )
        await coordinator.async_refresh()
        assert hass.states.get(sensor.entity_id).state == "0.0"
        assert not sensor.assumed_state
        fetch.return_value = SimpleNamespace(
            value_0=None, value_1=0, dtu_info=SimpleNamespace(dfs=0)
        )
        await coordinator.async_refresh()
        assert hass.states.get(sensor.entity_id).state == "unavailable"
    remove_listener()
    await coordinator.async_shutdown()
