"""Regression tests for brief outages and missing live measurements."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hoymiles_wifi.const import CONF_DTU_SERIAL_NUMBER, DOMAIN
from custom_components.hoymiles_wifi.coordinator import (
    HoymilesEnergyStorageUpdateCoordinator,
    HoymilesRealDataUpdateCoordinator,
)
from custom_components.hoymiles_wifi.sensor import (
    HoymilesDataSensorEntity,
    HoymilesEnergySensorEntity,
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
        assert (await refresh()).state == "unknown"
        assert sensor.available

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


async def test_daily_maximum_survives_missing_values(live_sensor, freezer):
    """Missing measurements stay unknown without losing the day's counter peak."""
    coordinator, fetch, original = live_sensor
    sensor = type(original)(
        original._config_entry,
        HoymilesSensorEntityDescription(
            key=original.entity_description.key,
            serial_number="4143A01B0514",
            is_dtu_sensor=True,
            force_keep_maximum_within_day=True,
        ),
        coordinator,
    )
    for raw, expected in [(100, 100), (None, None), (90, 100), (110, 110)]:
        fetch.return_value = SimpleNamespace(power=raw)
        await coordinator.async_refresh()
        sensor.update_state_value()
        assert sensor.native_value == expected
    freezer.tick(timedelta(days=1))
    fetch.return_value = SimpleNamespace(power=5)
    await coordinator.async_refresh()
    sensor.update_state_value()
    assert sensor.native_value == 5
    await coordinator.async_shutdown()


async def test_energy_counter_protection(live_sensor):
    """Counter protection is independent of the transport grace period."""
    coordinator, fetch, original = live_sensor
    sensor = HoymilesEnergySensorEntity(
        original._config_entry,
        original.entity_description,
        coordinator,
    )
    for raw, expected in [(100, 10.0), (None, None), (0, 10.0), (120, 12.0)]:
        fetch.return_value = SimpleNamespace(power=raw)
        await coordinator.async_refresh()
        sensor.update_state_value()
        assert sensor.native_value == expected
    await coordinator.async_shutdown()


def test_midnight_reset_delay_across_dst(hass, live_sensor):
    """Schedule the daily reset at local midnight even on a short DST day."""
    coordinator, _, original = live_sensor
    sensor = HoymilesEnergySensorEntity(
        original._config_entry,
        original.entity_description,
        coordinator,
    )
    sensor.hass = hass
    vienna = ZoneInfo("Europe/Vienna")
    with (
        patch(
            "custom_components.hoymiles_wifi.sensor.dt_util.DEFAULT_TIME_ZONE", vienna
        ),
        patch(
            "custom_components.hoymiles_wifi.sensor.dt_util.now",
            return_value=datetime(2026, 3, 29, 0, 30, tzinfo=vienna),
        ),
        patch(
            "custom_components.hoymiles_wifi.sensor.dt_util.utcnow",
            return_value=datetime(2026, 3, 28, 23, 30, tzinfo=UTC),
        ),
        patch.object(hass.loop, "call_later") as call_later,
    ):
        sensor.schedule_midnight_reset(reset_sensor_value=False)

    assert call_later.call_args.args[0] == 22.5 * 60 * 60
