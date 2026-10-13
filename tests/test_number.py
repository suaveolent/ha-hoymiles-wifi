"""Tests for persistent and temporary inverter power limits."""

from dataclasses import replace
from datetime import timedelta
from unittest.mock import AsyncMock, Mock, patch

from homeassistant.exceptions import HomeAssistantError
from hoymiles_wifi.const import CMD_ACTION_LIMIT_POWER, CMD_ACTION_LIMIT_POWER_TEMPORARY
from hoymiles_wifi.dtu import DTU
from hoymiles_wifi.hoymiles import convert_inverter_serial_number
from hoymiles_wifi.protobuf import CommandPB_pb2, GetConfig_pb2, RealDataNew_pb2
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hoymiles_wifi.const import (
    CONF_DTU_SERIAL_NUMBER,
    CONF_INVERTERS,
    CONF_THREE_PHASE_INVERTERS,
    DOMAIN,
    HASS_CONFIG_COORDINATOR,
    HASS_DATA_COORDINATOR,
)
from custom_components.hoymiles_wifi.coordinator import (
    HoymilesConfigUpdateCoordinator,
    HoymilesRealDataUpdateCoordinator,
)
from custom_components.hoymiles_wifi.number import (
    CONFIG_CONTROL_ENTITIES,
    HoymilesNumberEntity,
    SetAction,
    async_setup_entry,
)


@pytest.fixture
def power_controls(hass):
    """Create real entities and a DTU with only its network transport mocked."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_DTU_SERIAL_NUMBER: "4143A01B0514", CONF_INVERTERS: ["112400000001"]},
    )
    entry.add_to_hass(hass)
    dtu = DTU("dtu.local")
    dtu.async_send_request = AsyncMock(
        return_value=CommandPB_pb2.CommandReqDTO(
            action=CMD_ACTION_LIMIT_POWER_TEMPORARY
        )
    )
    coordinator = HoymilesConfigUpdateCoordinator(
        hass, dtu, entry, timedelta(seconds=300)
    )
    coordinator.data = GetConfig_pb2.GetConfigReqDTO(limit_power_mypower=600)
    coordinator.async_request_refresh = AsyncMock()
    live_coordinator = HoymilesRealDataUpdateCoordinator(
        hass, dtu, entry, timedelta(seconds=35)
    )
    live_coordinator.async_request_refresh = AsyncMock()
    dtu.async_get_real_data_new = AsyncMock()
    entities = [
        HoymilesNumberEntity(
            entry,
            replace(description, serial_number=entry.data[CONF_DTU_SERIAL_NUMBER]),
            live_coordinator
            if description.set_action == SetAction.POWER_LIMIT_TEMPORARY
            else coordinator,
            live_coordinator,
        )
        for description in CONFIG_CONTROL_ENTITIES
    ]
    return entry, coordinator, dtu, entities


@pytest.mark.parametrize(
    ("watts", "encoded", "displayed"),
    [(0.1, 1, 0.1), (300, 3000, 300), (12.35, 124, 12.4), (3276.7, 32767, 3276.7)],
)
async def test_temporary_command_and_readback(
    hass, power_controls, watts, encoded, displayed
):
    """Send the runtime command and do not overwrite watts with persistent percent."""
    _, coordinator, dtu, (persistent, temporary) = power_controls
    assert persistent.native_value == 60
    assert temporary.native_value is None

    await temporary.async_set_native_value(watts)

    _, request, _ = dtu.async_send_request.call_args.args
    assert request.action == CMD_ACTION_LIMIT_POWER_TEMPORARY
    assert request.data == f"S:1,P:{encoded}\r"
    assert temporary.native_value == displayed
    assert temporary.assumed_state
    assert persistent.native_value == 60
    coordinator.async_request_refresh.assert_not_awaited()
    temporary.coordinator.async_request_refresh.assert_awaited_once()

    coordinator.data.limit_power_mypower = 800
    persistent.update_state_value()
    temporary.update_state_value()
    assert persistent.native_value == 80
    assert temporary.native_value == displayed
    assert temporary.assumed_state

    reloaded_coordinator = HoymilesRealDataUpdateCoordinator(
        hass, dtu, temporary._config_entry, timedelta(seconds=35)
    )
    reloaded = HoymilesNumberEntity(
        temporary._config_entry,
        temporary.entity_description,
        reloaded_coordinator,
        reloaded_coordinator,
    )
    assert reloaded.native_value is None
    assert not reloaded.assumed_state


async def test_persistent_control_uses_existing_command(power_controls):
    """Keep the existing percentage command and refresh behavior."""
    _, coordinator, dtu, (persistent, temporary) = power_controls
    await persistent.async_set_native_value(50)
    _, request, _ = dtu.async_send_request.call_args.args
    assert request.action == CMD_ACTION_LIMIT_POWER
    assert request.data == "A:500,B:0,C:0\r"
    coordinator.async_request_refresh.assert_awaited_once()
    assert persistent.native_value == 50
    assert temporary.native_value is None


@pytest.mark.parametrize("response", [None, CommandPB_pb2.CommandReqDTO(err_code=1)])
async def test_failed_temporary_command_keeps_previous_value(power_controls, response):
    """Do not report success or fall back to EEPROM writes after a failed command."""
    _, coordinator, dtu, (_, temporary) = power_controls
    dtu.async_send_request.return_value = response
    with pytest.raises(HomeAssistantError):
        await temporary.async_set_native_value(300)
    assert temporary.native_value is None
    assert not temporary.assumed_state
    dtu.async_send_request.assert_awaited_once()
    assert (
        dtu.async_send_request.call_args.args[1].action
        == CMD_ACTION_LIMIT_POWER_TEMPORARY
    )
    coordinator.async_request_refresh.assert_not_awaited()

    dtu.async_send_request.return_value = CommandPB_pb2.CommandReqDTO(err_code=0)
    await temporary.async_set_native_value(100)
    dtu.async_send_request.return_value = response
    with pytest.raises(HomeAssistantError):
        await temporary.async_set_native_value(200)
    assert temporary.native_value == 100
    assert temporary.assumed_state


@pytest.mark.parametrize(
    ("index", "value"),
    [
        (0, -1),
        (0, 101),
        (1, 0),
        (1, -1),
        (1, 3276.8),
        (1, float("nan")),
        (1, float("inf")),
        (1, True),
    ],
)
async def test_invalid_power_limits_do_not_send_commands(power_controls, index, value):
    """Reject invalid values before contacting the DTU."""
    _, coordinator, dtu, entities = power_controls
    with pytest.raises(HomeAssistantError, match="out of range"):
        await entities[index].async_set_native_value(value)
    dtu.async_send_request.assert_not_awaited()
    coordinator.async_request_refresh.assert_not_awaited()


@pytest.mark.parametrize(
    ("serial", "inverters", "three_phase", "expected"),
    [
        ("4143A01B0514", ["112400000001"], [], 2),
        ("4143A01B0514", [], ["112400000001"], 2),
        ("411000000001", ["112400000001"], [], 1),
        ("4143A01B0514", [], [], 0),
    ],
)
async def test_power_control_setup(
    hass, power_controls, serial, inverters, three_phase, expected
):
    """Offer the temporary control for integrated WiFi DTUs only."""
    _, coordinator, _, (_, temporary) = power_controls
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_DTU_SERIAL_NUMBER: serial,
            CONF_INVERTERS: inverters,
            CONF_THREE_PHASE_INVERTERS: three_phase,
        },
    )
    entry.add_to_hass(hass)
    hass.data[DOMAIN] = {
        entry.entry_id: {
            HASS_CONFIG_COORDINATOR: coordinator,
            HASS_DATA_COORDINATOR: temporary.coordinator,
        }
    }
    add_entities = Mock()
    await async_setup_entry(hass, entry, add_entities)
    if expected:
        assert len(add_entities.call_args.args[0]) == expected
    else:
        add_entities.assert_not_called()


def power_limit_echo(raw_limit, serial="112400000001"):
    """Return a live response with an inverter limit echo, when present."""
    response = RealDataNew_pb2.RealDataNewReqDTO(device_serial_number="4143A01B0514")
    if raw_limit is not None:
        response.sgs_data.add(
            serial_number=convert_inverter_serial_number(serial), power_limit=raw_limit
        )
    return response


async def test_live_echo_confirms_watts_and_persistent_command_clears_them(
    power_controls,
):
    """Keep ambiguous percentage echoes out of the temporary watt control."""
    _, _, dtu, (persistent, temporary) = power_controls
    live = temporary.coordinator
    remove_listener = live.async_add_listener(temporary.update_state_value)

    async def echo(raw):
        dtu.async_get_real_data_new.return_value = power_limit_echo(raw)
        await live.async_refresh()

    await echo(600)
    assert temporary.native_value is None

    await temporary.async_set_native_value(300)
    await echo(600)
    assert temporary.native_value == 300
    assert temporary.assumed_state

    await echo(3000)
    assert temporary.native_value == 300
    assert not temporary.assumed_state
    assert persistent.native_value == 60

    await echo(2800)
    assert temporary.native_value == 280
    assert not temporary.assumed_state

    await persistent.async_set_native_value(50)
    assert temporary.native_value is None
    await echo(500)
    assert temporary.native_value is None
    assert not temporary.assumed_state

    remove_listener()
    await live.async_shutdown()


@pytest.mark.parametrize(
    ("raw", "serial"),
    [
        (None, "112400000001"),
        (0, "112400000001"),
        (32768, "112400000001"),
        (3000, "112400000002"),
    ],
)
async def test_missing_or_invalid_echo_is_unknown(power_controls, raw, serial):
    """Do not confirm missing, invalid, or another inverter's limit."""
    _, _, dtu, (_, temporary) = power_controls
    live = temporary.coordinator
    remove_listener = live.async_add_listener(temporary.update_state_value)
    await temporary.async_set_native_value(300)
    dtu.async_get_real_data_new.return_value = power_limit_echo(raw, serial)
    await live.async_refresh()
    assert temporary.native_value is None
    assert not temporary.assumed_state

    dtu.async_get_real_data_new.return_value = power_limit_echo(3000)
    await live.async_refresh()
    assert temporary.native_value == 300
    assert not temporary.assumed_state
    remove_listener()
    await live.async_shutdown()


async def test_failed_persistent_command_preserves_watt_interpretation(power_controls):
    """A rejected percent command must not discard a valid watt echo."""
    _, _, dtu, (persistent, temporary) = power_controls
    live = temporary.coordinator
    remove_listener = live.async_add_listener(temporary.update_state_value)
    await temporary.async_set_native_value(300)
    dtu.async_get_real_data_new.return_value = power_limit_echo(3000)
    await live.async_refresh()
    dtu.async_send_request.return_value = None
    with pytest.raises(HomeAssistantError):
        await persistent.async_set_native_value(50)
    assert temporary.native_value == 300
    assert not temporary.assumed_state
    remove_listener()
    await live.async_shutdown()


async def test_cached_outage_echo_does_not_confirm_new_command(power_controls):
    """Confirm only fresh echoes and use the existing outage grace period."""
    _, _, dtu, (_, temporary) = power_controls
    live = temporary.coordinator
    remove_listener = live.async_add_listener(temporary.update_state_value)
    with patch(
        "custom_components.hoymiles_wifi.coordinator.monotonic", return_value=0
    ) as clock:
        await temporary.async_set_native_value(300)
        dtu.async_get_real_data_new.return_value = power_limit_echo(3000)
        await live.async_refresh()
        assert not temporary.assumed_state

        await temporary.async_set_native_value(200)
        clock.return_value = 35
        dtu.async_get_real_data_new.return_value = None
        await live.async_refresh()
        assert temporary.native_value == 200
        assert temporary.assumed_state
        assert temporary.available

        clock.return_value = 180
        await live.async_refresh()
        assert not temporary.available

        dtu.async_get_real_data_new.return_value = power_limit_echo(2000)
        await live.async_refresh()
        assert temporary.native_value == 200
        assert not temporary.assumed_state
        assert temporary.available

    remove_listener()
    await live.async_shutdown()


async def test_no_microinverters_needs_no_live_coordinator(hass):
    """Skip power controls for a hybrid-only entry with no real-data coordinator."""
    entry = MockConfigEntry(
        domain=DOMAIN, data={CONF_DTU_SERIAL_NUMBER: "4143A01B0514"}
    )
    entry.add_to_hass(hass)
    hass.data[DOMAIN] = {entry.entry_id: {}}
    add_entities = Mock()
    await async_setup_entry(hass, entry, add_entities)
    add_entities.assert_not_called()
