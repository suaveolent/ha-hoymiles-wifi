"""Tests for how an unreachable DTU is reported."""

from datetime import timedelta
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

from homeassistant.helpers import update_coordinator
from homeassistant.helpers.update_coordinator import UpdateFailed
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hoymiles_wifi import coordinator as coordinator_module
from custom_components.hoymiles_wifi.const import CONF_DTU_SERIAL_NUMBER, DOMAIN
from custom_components.hoymiles_wifi.coordinator import (
    HoymilesRealDataUpdateCoordinator,
)

CORE_SUPPORTS_UNREACHABLE = hasattr(update_coordinator, "UpdateFailedUnreachable")


@pytest.fixture
def unreachable_coordinator(hass):
    """Create a live data coordinator whose DTU never answers."""
    entry = MockConfigEntry(
        domain=DOMAIN, data={CONF_DTU_SERIAL_NUMBER: "4143A01B0514"}
    )
    entry.add_to_hass(hass)
    dtu = SimpleNamespace(async_get_real_data_new=AsyncMock(side_effect=TimeoutError))
    return HoymilesRealDataUpdateCoordinator(
        hass, dtu, entry, update_interval=timedelta(seconds=35)
    )


async def test_unreachable_dtu_raises_unreachable(hass, unreachable_coordinator):
    """A silent DTU is reported as unreachable, which is still an UpdateFailed."""
    with pytest.raises(
        coordinator_module.UpdateFailedUnreachable,
        match="Unable to retrieve live data from DTU",
    ) as err:
        await unreachable_coordinator._async_update_data()
    assert isinstance(err.value, UpdateFailed)
    await unreachable_coordinator.async_shutdown()


def test_fallback_matches_core():
    """Without core support the integration falls back to UpdateFailed."""
    expected = (
        update_coordinator.UpdateFailedUnreachable
        if CORE_SUPPORTS_UNREACHABLE
        else UpdateFailed
    )
    assert coordinator_module.UpdateFailedUnreachable is expected


@pytest.mark.skipif(
    not CORE_SUPPORTS_UNREACHABLE,
    reason="Home Assistant core without UpdateFailedUnreachable",
)
async def test_unreachable_dtu_is_logged_at_info(hass, unreachable_coordinator, caplog):
    """An unreachable DTU (for example at night) does not produce an error log."""
    caplog.set_level(logging.DEBUG, logger=coordinator_module.__name__)
    await unreachable_coordinator.async_refresh()

    assert not unreachable_coordinator.last_update_success
    records = [
        record
        for record in caplog.records
        if record.name == coordinator_module.__name__
        and "Unable to retrieve live data from DTU" in record.getMessage()
    ]
    assert records
    assert all(record.levelno == logging.INFO for record in records)
    await unreachable_coordinator.async_shutdown()
