"""Tests for explicitly enabled offline estimates and retained energy totals."""

from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import UnitOfEnergy
from homeassistant.util import dt as dt_util
from hoymiles_wifi.dtu import NetworkState
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.hoymiles_wifi.const import (
    CONF_DTU_SERIAL_NUMBER,
    CONF_OFFLINE_FALLBACK,
    DOMAIN,
)
from custom_components.hoymiles_wifi.coordinator import (
    HoymilesEnergyStorageUpdateCoordinator,
    HoymilesRealDataUpdateCoordinator,
)
from custom_components.hoymiles_wifi.sensor import (
    HoymilesDataSensorEntity,
    HoymilesEnergySensorEntity,
    HoymilesSensorEntityDescription,
)


@pytest.fixture(params=[False, True], ids=["regular", "hybrid"])
async def offline_sensor(hass, request):
    """Use actual coordinators with synthetic transport replies and an opt-in entry."""
    hybrid = request.param
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_DTU_SERIAL_NUMBER: "4143A6B7C8D9",
            CONF_OFFLINE_FALLBACK: True,
        },
    )
    entry.add_to_hass(hass)
    fetch = AsyncMock(return_value=None)
    dtu = SimpleNamespace(
        get_state=Mock(return_value=NetworkState.Offline),
        async_get_real_data_new=fetch,
        async_get_energy_storage_data=fetch,
    )
    coordinator_class = (
        HoymilesEnergyStorageUpdateCoordinator
        if hybrid
        else HoymilesRealDataUpdateCoordinator
    )
    kwargs = (
        {"dtu_serial_number": 123, "inverters": [{"inverter_serial_number": 456}]}
        if hybrid
        else {}
    )
    coordinator = coordinator_class(hass, dtu, entry, timedelta(seconds=35), **kwargs)
    description = HoymilesSensorEntityDescription(
        key="[0].reading" if hybrid else "reading",
        serial_number="4143A6B7C8D9",
        is_dtu_sensor=True,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
    )
    created = []

    def make_sensor(kind="power"):
        """Create energy variants with native Wh and no measurement scaling."""
        current = description
        if kind in ("daily", "lifetime"):
            current = replace(
                description,
                device_class=SensorDeviceClass.ENERGY,
                state_class=SensorStateClass.TOTAL_INCREASING,
                native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
                conversion_factor=None,
                is_daily_energy=kind == "daily",
            )
        sensor_class = (
            HoymilesEnergySensorEntity
            if kind in ("daily", "lifetime")
            else HoymilesDataSensorEntity
        )
        sensor = sensor_class(entry, current, coordinator)
        sensor.hass = hass
        sensor.entity_id = f"sensor.test_offline_{kind}"
        created.append(sensor)
        return sensor

    yield entry, coordinator, fetch, dtu, make_sensor
    for sensor in created:
        if sensor._on_remove:
            await sensor.async_remove(force_remove=True)
    await coordinator.async_shutdown()


async def test_zero_fallback_respects_grace_and_recovery(hass, offline_sensor):
    """Use cached live data first, estimate zero only when offline, then recover."""
    entry, coordinator, fetch, dtu, make_sensor = offline_sensor
    sensor = make_sensor()
    with patch(
        "custom_components.hoymiles_wifi.coordinator.monotonic", return_value=0
    ) as clock:
        fetch.return_value = SimpleNamespace(reading=250)
        await coordinator.async_refresh()
        sensor.update_state_value()
        assert sensor.native_value == 25
        fetch.return_value = None
        clock.return_value = 179
        await coordinator.async_refresh()
        assert sensor.native_value == 25
        assert sensor.available
        clock.return_value = 180
        await coordinator.async_refresh()
        assert sensor.native_value == 0
        assert sensor.available
        assert sensor.assumed_state
        sensor.async_write_ha_state()
        assert hass.states.get(sensor.entity_id).state == "0"
        assert hass.states.get(sensor.entity_id).attributes["assumed_state"] is True
        dtu.get_state.return_value = NetworkState.Unknown
        assert not sensor.available
        dtu.get_state.return_value = NetworkState.Offline
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, CONF_OFFLINE_FALLBACK: False}
        )
        assert not sensor.available
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, CONF_OFFLINE_FALLBACK: True}
        )
        fetch.return_value = SimpleNamespace(reading=80)
        await coordinator.async_refresh()
        sensor.update_state_value()
        assert sensor.native_value == 8
        assert not sensor.assumed_state
        fetch.return_value = SimpleNamespace(reading=None)
        await coordinator.async_refresh()
        sensor.update_state_value()
        assert not sensor.available


async def test_known_energy_is_retained_instead_of_zero(offline_sensor):
    """Keep reported lifetime and daily energy when a successful DTU becomes offline."""
    _, coordinator, fetch, _, make_sensor = offline_sensor
    daily, lifetime = make_sensor("daily"), make_sensor("lifetime")
    fetch.return_value = SimpleNamespace(reading=1234)
    await coordinator.async_refresh()
    for sensor in (daily, lifetime):
        sensor.update_state_value()
    fetch.return_value = None
    coordinator._last_successful_fetch -= 181
    await coordinator.async_refresh()
    for sensor in (daily, lifetime):
        assert sensor.native_value == 1234
        assert sensor.available
        assert sensor.assumed_state
    fetch.return_value = SimpleNamespace(reading=0)
    await coordinator.async_refresh()
    for sensor in (daily, lifetime):
        sensor.update_state_value()
    assert daily.native_value == 0
    assert not daily.assumed_state
    assert lifetime.native_value == 1234
    assert lifetime.assumed_state


async def test_offline_startup_does_not_zero_unknown_lifetime_totals(offline_sensor):
    """Estimate power and daily energy, but leave unknown lifetime totals unavailable."""
    _, coordinator, _, _, make_sensor = offline_sensor
    power, daily, lifetime = (
        make_sensor(),
        make_sensor("daily"),
        make_sensor("lifetime"),
    )
    await coordinator.async_refresh()
    assert power.native_value == 0
    assert power.available
    assert daily.native_value == 0
    assert daily.available
    assert daily.assumed_state
    assert lifetime.native_value is None
    assert not lifetime.available
    diagnostic = make_sensor()
    diagnostic.entity_description = replace(
        diagnostic.entity_description, state_class=None
    )
    assert not diagnostic.available


async def test_daily_fallback_updates_at_local_midnight(hass, freezer, offline_sensor):
    """Keep today's in-memory total until the midnight callback updates its state."""
    _, coordinator, fetch, _, make_sensor = offline_sensor
    await hass.config.async_set_time_zone("Europe/Vienna")
    freezer.move_to("2026-11-13T22:59:59+00:00")
    sensor = make_sensor("daily")
    fetch.return_value = SimpleNamespace(reading=1234)
    await coordinator.async_refresh()
    sensor.update_state_value()
    fetch.return_value = None
    coordinator._last_successful_fetch -= 181
    await coordinator.async_refresh()
    sensor.platform = SimpleNamespace(platform_name=DOMAIN, config_entry=None)
    await sensor.add_to_platform_finish()
    assert hass.states.get(sensor.entity_id).state == "1234"
    freezer.tick(timedelta(seconds=1))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done(wait_background_tasks=True)
    assert hass.states.get(sensor.entity_id).state == "0"
    assert sensor._last_energy_value == 1234


async def test_new_sensor_does_not_restore_previous_energy(offline_sensor):
    """A new runtime starts at zero, even if the previous runtime had a total."""
    _, coordinator, fetch, _, make_sensor = offline_sensor
    previous = make_sensor("daily")
    fetch.return_value = SimpleNamespace(reading=1234)
    await coordinator.async_refresh()
    previous.update_state_value()
    fetch.return_value = None
    coordinator._last_successful_fetch -= 181
    await coordinator.async_refresh()
    assert previous.native_value == 1234
    coordinator.data = None
    restarted = make_sensor("daily")
    assert restarted.native_value == 0
    assert restarted.available
    assert restarted.assumed_state


async def test_midnight_rollover_during_short_outage(hass, freezer, offline_sensor):
    """A short outage may retain measurements, but yesterday's daily total expires."""
    _, coordinator, fetch, _, make_sensor = offline_sensor
    await hass.config.async_set_time_zone("Europe/Vienna")
    freezer.move_to("2026-11-13T22:59:59+00:00")
    daily, lifetime = make_sensor("daily"), make_sensor("lifetime")
    fetch.return_value = SimpleNamespace(reading=1234)
    await coordinator.async_refresh()
    for sensor in (daily, lifetime):
        sensor.update_state_value()
    fetch.return_value = None
    await coordinator.async_refresh()
    assert coordinator.last_update_success
    assert daily.native_value == 1234
    freezer.tick(timedelta(seconds=1))
    assert daily.native_value == 0
    assert lifetime.native_value == 1234
    assert daily.assumed_state
