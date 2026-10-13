"""Tests for scheduled cloud upload quiet windows and cached-data freshness."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from homeassistant.helpers.update_coordinator import UpdateFailed
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hoymiles_wifi.const import CONF_CLOUD_PAUSE, DOMAIN
from custom_components.hoymiles_wifi.coordinator import (
    HoymilesAppInfoUpdateCoordinator,
    HoymilesConfigUpdateCoordinator,
    HoymilesEnergyStorageUpdateCoordinator,
    HoymilesRealDataUpdateCoordinator,
)


@pytest.mark.parametrize(
    "coordinator_type",
    [
        HoymilesRealDataUpdateCoordinator,
        HoymilesConfigUpdateCoordinator,
        HoymilesAppInfoUpdateCoordinator,
        HoymilesEnergyStorageUpdateCoordinator,
    ],
)
async def test_pause_skips_requests_without_extending_outage_grace(
    hass, coordinator_type
):
    """All pollers share quiet windows, preserve fresh caches, and recover after them."""
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_CLOUD_PAUSE: 30})
    entry.add_to_hass(hass)
    args = (
        {"dtu_serial_number": 123, "inverters": []}
        if coordinator_type is HoymilesEnergyStorageUpdateCoordinator
        else {}
    )
    coordinator = coordinator_type(
        hass, SimpleNamespace(), entry, timedelta(seconds=35), **args
    )
    response = SimpleNamespace(value=0)
    fetch = coordinator._async_fetch_data = AsyncMock(return_value=response)
    with (
        patch(
            "custom_components.hoymiles_wifi.coordinator.dt_util.utcnow",
            return_value=datetime(2026, 10, 13, 12, 4, 49, tzinfo=UTC),
        ) as now,
        patch(
            "custom_components.hoymiles_wifi.coordinator.monotonic", return_value=0
        ) as clock,
    ):
        await coordinator.async_refresh()
        assert coordinator.data is response
        assert not coordinator.data_is_stale
        fetch.assert_awaited_once()
        fetch.reset_mock()

        now.return_value = datetime(2026, 10, 13, 12, 4, 50, tzinfo=UTC)
        clock.return_value = 35
        await coordinator.async_refresh()
        assert coordinator.data is response
        assert coordinator.data_is_stale
        assert coordinator.last_update_success
        assert coordinator._last_successful_fetch == 0
        fetch.assert_not_awaited()

        now.return_value = datetime(2026, 10, 13, 12, 5, 19, tzinfo=UTC)
        clock.return_value = 180
        await coordinator.async_refresh()
        assert not coordinator.last_update_success
        fetch.assert_not_awaited()

        now.return_value = datetime(2026, 10, 13, 12, 5, 20, tzinfo=UTC)
        await coordinator.async_refresh()
        fetch.assert_awaited_once()
        assert coordinator.last_update_success
        assert not coordinator.data_is_stale

        now.return_value = datetime(2026, 10, 13, 12, 9, 50, tzinfo=UTC)
        coordinator.data = None
        fetch.reset_mock()
        with pytest.raises(UpdateFailed, match="cloud upload pause"):
            await coordinator._async_update_data()
        fetch.assert_not_awaited()
    await coordinator.async_shutdown()


@pytest.mark.parametrize("data", [{}, {CONF_CLOUD_PAUSE: 0}])
async def test_cloud_pause_disabled_by_default(hass, data):
    """Existing installations continue to poll normally during cloud update windows."""
    entry = MockConfigEntry(domain=DOMAIN, data=data)
    entry.add_to_hass(hass)
    coordinator = HoymilesRealDataUpdateCoordinator(
        hass, SimpleNamespace(), entry, timedelta(seconds=35)
    )
    fetch = coordinator._async_fetch_data = AsyncMock(
        return_value=SimpleNamespace(value=0)
    )
    with patch(
        "custom_components.hoymiles_wifi.coordinator.dt_util.utcnow",
        return_value=datetime(2026, 10, 13, 12, 4, 50, tzinfo=UTC),
    ):
        await coordinator.async_refresh()
        fetch.assert_awaited_once()
        assert coordinator.last_update_success
        assert not coordinator.data_is_stale
    await coordinator.async_shutdown()
