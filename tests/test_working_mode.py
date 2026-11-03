"""Tests for hybrid working-mode readback, settings, and update scheduling."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.const import CONF_HOST
from homeassistant.core import ServiceCall
from homeassistant.helpers import device_registry as dr
from hoymiles_wifi.dtu import DTU
from hoymiles_wifi.protobuf import ESData_pb2, ESParaSet_pb2
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hoymiles_wifi.const import (
    CONF_CLOUD_PAUSE,
    CONF_DTU_SERIAL_NUMBER,
    CONF_HYBRID_INVERTERS,
    CONF_INVERTERS,
    CONF_PORTS,
    CONF_UPDATE_INTERVAL,
    CONFIG_VERSION,
    DOMAIN,
    HASS_DTU,
    HASS_ENERGY_STORAGE_CONFIG_COORDINATOR,
    HASS_ENERGY_STORAGE_DATA_COORDINATOR,
)
from custom_components.hoymiles_wifi.coordinator import (
    HoymilesEnergyStorageConfigUpdateCoordinator,
)
from custom_components.hoymiles_wifi.sensor import async_setup_entry
from custom_components.hoymiles_wifi.services import async_handle_set_bms_mode

DTU_SERIAL = "1234567800000001"
INVERTERS = [
    {"inverter_serial_number": "1234567800000002", "model_name": "HYT-5.0HV-EUG1"},
    {"inverter_serial_number": "1234567800000003", "model_name": "HYT-5.0HV-EUG1"},
]


def configuration(mode=1, reserve_soc=10):
    """Build a reported self-consumption configuration with synthetic values."""
    response = ESParaSet_pb2.ESParaSetBO()
    response.emspara.mode = mode
    response.emspara.selfu.rev_soc = reserve_soc
    return response


@pytest.fixture
def working_mode(hass):
    """Create the coordinator used by the actual sensor platform."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_DTU_SERIAL_NUMBER: DTU_SERIAL,
            CONF_HYBRID_INVERTERS: INVERTERS,
            CONF_INVERTERS: [],
            CONF_PORTS: [],
            CONF_CLOUD_PAUSE: 30,
        },
    )
    entry.add_to_hass(hass)
    dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={(DOMAIN, DTU_SERIAL)}
    )
    dtu = SimpleNamespace(async_get_energy_storage_working_mode=AsyncMock())
    coordinator = HoymilesEnergyStorageConfigUpdateCoordinator(
        hass, dtu, entry, timedelta(minutes=5), DTU_SERIAL, INVERTERS
    )
    hass.data[DOMAIN] = {
        entry.entry_id: {
            HASS_ENERGY_STORAGE_CONFIG_COORDINATOR: coordinator,
            HASS_ENERGY_STORAGE_DATA_COORDINATOR: coordinator,
        }
    }
    return entry, coordinator, dtu.async_get_energy_storage_working_mode


async def test_sensor_platform_and_reported_modes(hass, working_mode):
    """Create one translated enum sensor per hybrid, with the reported settings."""
    entry, coordinator, fetch = working_mode
    coordinator.async_set_updated_data([configuration(), configuration(3, 0)])
    sensors = []
    await async_setup_entry(hass, entry, sensors.extend)
    modes = [sensor for sensor in sensors if sensor.translation_key == "working_mode"]
    assert len(modes) == 2
    for sensor in modes:
        sensor.hass = hass
    assert modes[0].native_value == "self_use"
    assert modes[1].native_value == "backup_power"
    assert modes[0].device_class == SensorDeviceClass.ENUM
    assert "time_of_use" in modes[0].options
    assert modes[0].extra_state_attributes["settings"]["selfu"]["rev_soc"] == 10
    assert modes[1].extra_state_attributes["settings"]["selfu"]["rev_soc"] == 0
    assert modes[0].device_info["identifiers"] == {
        (DOMAIN, INVERTERS[0]["inverter_serial_number"])
    }
    fetch.assert_not_awaited()

    coordinator.async_set_updated_data([configuration(8), None])
    for sensor in modes:
        sensor.update_state_value()
    assert modes[0].native_value == "time_of_use"
    assert not modes[1].available
    assert modes[1].extra_state_attributes is None

    coordinator.async_set_updated_data([configuration(99), ESParaSet_pb2.ESParaSetBO()])
    for sensor in modes:
        sensor.update_state_value()
    assert modes[0].native_value is None
    assert modes[0].available
    assert modes[0].extra_state_attributes["settings"]["mode"] == 99
    assert not modes[1].available


@pytest.mark.parametrize("failure", [None, TimeoutError(), OSError("offline")])
async def test_polling_missing_devices_and_recovery(hass, working_mode, failure):
    """Keep replies associated with their inverter and recover after lost replies."""
    _, coordinator, fetch = working_mode
    first, second = configuration(), configuration(3)
    fetch.side_effect = [failure, second]
    await coordinator.async_refresh()
    assert coordinator.last_update_success
    assert coordinator.data == [None, second]
    assert fetch.call_args_list[0].kwargs == {
        "dtu_serial_number": int(DTU_SERIAL),
        "inverter_serial_number": int(INVERTERS[0]["inverter_serial_number"]),
    }
    assert fetch.call_args_list[1].kwargs["inverter_serial_number"] == int(
        INVERTERS[1]["inverter_serial_number"]
    )
    with patch(
        "custom_components.hoymiles_wifi.coordinator.monotonic", return_value=1000
    ) as clock:
        coordinator._last_successful_fetch = 0
        fetch.side_effect = [None, None]
        await coordinator.async_refresh()
        assert not coordinator.last_update_success
        clock.return_value = 1035
        fetch.side_effect = [first, second]
        await coordinator.async_refresh()
        assert coordinator.last_update_success
        assert coordinator.data == [first, second]


async def test_configuration_polling_respects_cloud_pause(hass, working_mode):
    """Use the shared quiet-window check rather than adding another pause mechanism."""
    _, coordinator, fetch = working_mode
    with patch(
        "custom_components.hoymiles_wifi.coordinator.dt_util.utcnow",
        return_value=datetime(2026, 11, 3, 12, 4, 50, tzinfo=UTC),
    ):
        await coordinator.async_refresh()
    fetch.assert_not_awaited()
    assert not coordinator.last_update_success
    assert coordinator.update_interval == timedelta(minutes=5)


async def test_set_mode_refreshes_readback_once_per_entry(hass, working_mode):
    """After setting multiple inverters, refresh their shared readback only once."""
    entry, coordinator, _ = working_mode
    coordinator.async_request_refresh = AsyncMock()
    dtu = DTU("unused")
    dtu.async_set_energy_storage_working_mode = AsyncMock()
    hass.data[DOMAIN][entry.entry_id].update(
        {HASS_DTU: dtu, CONF_DTU_SERIAL_NUMBER: DTU_SERIAL}
    )
    registry = dr.async_get(hass)
    devices = [
        registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, inverter["inverter_serial_number"])},
            serial_number=inverter["inverter_serial_number"],
        )
        for inverter in INVERTERS
    ]
    call = ServiceCall(
        hass,
        DOMAIN,
        "set_bms_mode",
        {
            "device_id": [device.id for device in devices],
            "bms_mode": "self_use",
            "rev_soc": 10,
        },
    )
    await async_handle_set_bms_mode(call)
    assert dtu.async_set_energy_storage_working_mode.await_count == 2
    coordinator.async_request_refresh.assert_awaited_once()


@pytest.mark.parametrize("supported", [True, False])
async def test_hybrid_setup_keeps_working_mode_optional(hass, supported):
    """Set up readback before platforms without blocking live data if unsupported."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=CONFIG_VERSION,
        data={
            CONF_HOST: "dtu.local",
            CONF_DTU_SERIAL_NUMBER: DTU_SERIAL,
            CONF_HYBRID_INVERTERS: INVERTERS,
            CONF_INVERTERS: [],
            CONF_UPDATE_INTERVAL: 35,
        },
    )
    entry.add_to_hass(hass)
    config = configuration() if supported else None

    async def forward_platforms(config_entry, platforms):
        coordinator = hass.data[DOMAIN][config_entry.entry_id][
            HASS_ENERGY_STORAGE_CONFIG_COORDINATOR
        ]
        assert coordinator.last_update_success is supported
        assert coordinator.data == ([config, config] if supported else None)
        assert coordinator.update_interval == timedelta(minutes=5)

    with (
        patch.object(
            DTU, "async_get_energy_storage_data", return_value=ESData_pb2.ESDataReqDTO()
        ),
        patch.object(
            DTU, "async_get_energy_storage_working_mode", return_value=config
        ) as readback,
        patch.object(
            hass.config_entries,
            "async_forward_entry_setups",
            side_effect=forward_platforms,
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        with patch.object(
            hass.config_entries, "async_unload_platforms", return_value=True
        ):
            assert await hass.config_entries.async_unload(entry.entry_id)
    assert readback.await_count == 2
