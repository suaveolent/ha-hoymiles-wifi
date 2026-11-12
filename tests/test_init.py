"""Test component setup."""

from datetime import timedelta
from unittest.mock import patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_HOST
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from hoymiles_wifi.dtu import DTU
from hoymiles_wifi.protobuf import (
    APPInfomationData_pb2,
    ESData_pb2,
    ESParaSet_pb2,
    GetConfig_pb2,
    RealDataNew_pb2,
)
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.hoymiles_wifi.const import (
    CONF_DTU_SERIAL_NUMBER,
    CONF_ENC_RAND,
    CONF_HYBRID_INVERTERS,
    CONF_INVERTERS,
    CONF_IS_ENCRYPTED,
    CONF_PORTS,
    CONF_UPDATE_INTERVAL,
    CONFIG_VERSION,
    DOMAIN,
    HASS_APP_INFO_COORDINATOR,
    HASS_CONFIG_COORDINATOR,
    HASS_DATA_COORDINATOR,
    HASS_ENERGY_STORAGE_CONFIG_COORDINATOR,
    HASS_ENERGY_STORAGE_DATA_COORDINATOR,
)


async def test_async_setup(hass):
    """Test the component gets setup."""

    assert await async_setup_component(hass, DOMAIN, {}) is True


@pytest.mark.parametrize("dfs", [1308623040, 0, None])
async def test_setup_refreshes_encryption_before_data(hass, dfs):
    """Repair stale encryption before polling, and preserve it across reloads."""
    enc_rand = "f5480938516c557e347bc49c672b6af1"
    encrypted = dfs == 1308623040
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=CONFIG_VERSION,
        data={
            CONF_HOST: "dtu.local",
            CONF_DTU_SERIAL_NUMBER: "4143A01B0514",
            CONF_UPDATE_INTERVAL: 35,
            CONF_INVERTERS: ["112345678901"],
            CONF_IS_ENCRYPTED: False,
            CONF_ENC_RAND: enc_rand,
        },
    )
    entry.add_to_hass(hass)
    requests = []
    app_info_modes = []
    dtu_device_ids = []

    async def forward_platforms(config_entry, platforms):
        """The parent must exist before any platform starts adding entities."""
        assert requests == ["app_info", "real_data", "config"]
        assert hass.data[DOMAIN][config_entry.entry_id][
            HASS_CONFIG_COORDINATOR
        ].update_interval == timedelta(minutes=5)
        device = dr.async_get(hass).async_get_device_by_identifier(
            (DOMAIN, config_entry.data[CONF_DTU_SERIAL_NUMBER]),
            config_entry.entry_id,
        )
        assert device is not None
        assert device.via_device_id is None
        assert device.manufacturer == "Hoymiles"
        dtu_device_ids.append(device.id)

    async def app_info(dtu):
        requests.append("app_info")
        app_info_modes.append(dtu.is_encrypted)
        if dfs is None:
            return None
        response = APPInfomationData_pb2.APPInfoDataReqDTO()
        response.dtu_info.dfs = dfs
        response.dtu_info.enc_rand = bytes.fromhex(enc_rand)
        return response

    async def real_data(dtu):
        requests.append("real_data")
        assert dtu.is_encrypted is encrypted
        if encrypted:
            assert dtu.enc_rand == bytes.fromhex(enc_rand)
        return RealDataNew_pb2.RealDataNewReqDTO(device_serial_number="4143A01B0514")

    async def config_data(dtu):
        requests.append("config")
        assert dtu.is_encrypted is encrypted
        return GetConfig_pb2.GetConfigReqDTO()

    with (
        patch.object(
            DTU, "async_app_information_data", autospec=True, side_effect=app_info
        ),
        patch.object(
            DTU, "async_get_real_data_new", autospec=True, side_effect=real_data
        ),
        patch.object(DTU, "async_get_config", autospec=True, side_effect=config_data),
        patch.object(
            hass.config_entries,
            "async_forward_entry_setups",
            side_effect=forward_platforms,
        ),
        patch.object(hass.config_entries, "async_unload_platforms", return_value=True),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        assert requests == ["app_info", "real_data", "config"]
        assert entry.data[CONF_IS_ENCRYPTED] is encrypted
        assert entry.data[CONF_ENC_RAND] == enc_rand

        requests.clear()
        assert await hass.config_entries.async_reload(entry.entry_id)
        assert requests == ["app_info", "real_data", "config"]
        assert app_info_modes == [False, encrypted]
        assert len(dtu_device_ids) == 2
        assert dtu_device_ids[0] == dtu_device_ids[1]

        assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize("failure", ["real_data", "hybrid"])
async def test_failed_initial_refresh_retries_before_platform_setup(
    hass, freezer, failure
):
    """Failed initial fetches must not leave platforms registered on a setup retry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=CONFIG_VERSION,
        data={
            CONF_HOST: "dtu.local",
            CONF_DTU_SERIAL_NUMBER: "414392349724",
            CONF_UPDATE_INTERVAL: 35,
            CONF_INVERTERS: ["112345678901"],
            CONF_HYBRID_INVERTERS: [{"inverter_serial_number": "112345678902"}],
        },
    )
    entry.add_to_hass(hass)
    app_info = APPInfomationData_pb2.APPInfoDataReqDTO()
    real_data = RealDataNew_pb2.RealDataNewReqDTO(device_serial_number="414392349724")
    config = GetConfig_pb2.GetConfigReqDTO()
    hybrid = real_data

    async def forward_platforms(config_entry, platforms):
        """Every required coordinator must have data before platforms are registered."""
        runtime = hass.data[DOMAIN][config_entry.entry_id]
        assert runtime[HASS_DATA_COORDINATOR].data is real_data
        assert runtime[HASS_CONFIG_COORDINATOR].data is config
        assert runtime[HASS_ENERGY_STORAGE_DATA_COORDINATOR].data == [hybrid]

    with (
        patch.object(DTU, "async_app_information_data", return_value=app_info),
        patch.object(
            DTU, "async_get_real_data_new", return_value=real_data
        ) as get_real,
        patch.object(DTU, "async_get_config", return_value=config),
        patch.object(
            DTU, "async_get_energy_storage_data", return_value=hybrid
        ) as get_hybrid,
        patch.object(DTU, "async_get_energy_storage_working_mode", return_value=None),
        patch.object(
            hass.config_entries,
            "async_forward_entry_setups",
            side_effect=forward_platforms,
        ) as forward,
        patch.object(hass.config_entries, "async_unload_platforms", return_value=True),
    ):
        failed_fetch = {
            "real_data": get_real,
            "hybrid": get_hybrid,
        }[failure]
        response = failed_fetch.return_value
        failed_fetch.return_value = None
        assert not await hass.config_entries.async_setup(entry.entry_id)
        assert entry.state is ConfigEntryState.SETUP_RETRY
        forward.assert_not_awaited()
        assert entry.entry_id not in hass.data[DOMAIN]
        assert not hass.services.has_service(DOMAIN, "set_bms_mode")

        failed_fetch.return_value = response
        freezer.tick(timedelta(seconds=6))
        async_fire_time_changed(hass, dt_util.utcnow())
        await hass.async_block_till_done()
        assert entry.state is ConfigEntryState.LOADED
        forward.assert_awaited_once()
        assert hass.services.has_service(DOMAIN, "set_bms_mode")
        assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize("failure", [None, TimeoutError(), OSError("unsupported")])
async def test_setup_tolerates_unsupported_config_command(hass, freezer, failure):
    """Missing optional configuration must not prevent working live entities loading."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=CONFIG_VERSION,
        data={
            CONF_HOST: "dtu.local",
            CONF_DTU_SERIAL_NUMBER: "411000000001",
            CONF_UPDATE_INTERVAL: 35,
            CONF_INVERTERS: ["112400000001"],
        },
    )
    entry.add_to_hass(hass)
    real = RealDataNew_pb2.RealDataNewReqDTO(device_serial_number="411000000001")
    listeners = []

    async def forward_platforms(config_entry, platforms):
        runtime = hass.data[DOMAIN][config_entry.entry_id]
        assert runtime[HASS_DATA_COORDINATOR].data is real
        assert runtime[HASS_DATA_COORDINATOR].last_update_success
        assert not runtime[HASS_CONFIG_COORDINATOR].last_update_success
        assert runtime[HASS_CONFIG_COORDINATOR].data is None
        assert runtime[HASS_CONFIG_COORDINATOR].update_interval is None
        listeners.append(
            runtime[HASS_CONFIG_COORDINATOR].async_add_listener(lambda: None)
        )

    with (
        patch.object(
            DTU,
            "async_app_information_data",
            return_value=APPInfomationData_pb2.APPInfoDataReqDTO(),
        ),
        patch.object(DTU, "async_get_real_data_new", return_value=real),
        patch.object(
            DTU, "async_get_config", return_value=None, side_effect=failure
        ) as get_config,
        patch.object(
            hass.config_entries,
            "async_forward_entry_setups",
            side_effect=forward_platforms,
        ) as forward,
        patch.object(hass.config_entries, "async_unload_platforms", return_value=True),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        assert entry.state is ConfigEntryState.LOADED
        forward.assert_awaited_once()
        freezer.tick(timedelta(minutes=15))
        async_fire_time_changed(hass, dt_util.utcnow())
        await hass.async_block_till_done()
        get_config.assert_awaited_once()
        for remove_listener in listeners:
            remove_listener()
        assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize("hybrid", [False, True], ids=["microinverter", "hybrid"])
@pytest.mark.parametrize("outcome", ["unload_offline", "recover", "unsupported_config"])
async def test_registered_dtu_loads_offline_and_recovers(
    hass, freezer, hybrid, outcome
):
    """Restore real entities at night and recover live data and metadata at sunrise."""
    serial = "1234567800000001" if hybrid else "4143A6B7C8D9"
    inverter = "1124A6B7C8D9"
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=CONFIG_VERSION,
        data={
            CONF_HOST: "dtu.local",
            CONF_DTU_SERIAL_NUMBER: serial,
            CONF_UPDATE_INTERVAL: 35,
            CONF_INVERTERS: [] if hybrid else [inverter],
            CONF_HYBRID_INVERTERS: [
                {
                    "inverter_serial_number": "1234567800000002",
                    "model_name": "HYT-5.0HV-EUG1",
                }
            ]
            if hybrid
            else [],
            CONF_PORTS: [],
        },
    )
    entry.add_to_hass(hass)
    dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={(DOMAIN, serial)}
    )
    with (
        patch.object(DTU, "async_app_information_data", return_value=None) as app_info,
        patch.object(DTU, "async_get_real_data_new", return_value=None) as real,
        patch.object(DTU, "async_get_config", return_value=None) as config,
        patch.object(
            DTU, "async_get_energy_storage_data", return_value=None
        ) as storage,
        patch.object(
            DTU, "async_get_energy_storage_working_mode", return_value=None
        ) as mode,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        assert entry.state is ConfigEntryState.LOADED
        runtime = hass.data[DOMAIN][entry.entry_id]
        live = runtime[
            HASS_ENERGY_STORAGE_DATA_COORDINATOR if hybrid else HASS_DATA_COORDINATOR
        ]
        metadata = runtime[
            HASS_ENERGY_STORAGE_CONFIG_COORDINATOR
            if hybrid
            else HASS_CONFIG_COORDINATOR
        ]
        assert not live.last_update_success
        assert live.data is None
        assert metadata.update_interval is None
        assert all(
            state.state == "unavailable"
            for state in hass.states.async_all()
            if state.entity_id.startswith(("sensor.", "number.", "binary_sensor."))
        )
        key = "[0].emspara" if hybrid else "dtu_daily_energy"
        sensor_id = er.async_get(hass).async_get_entity_id(
            "sensor", DOMAIN, f"hoymiles_{entry.entry_id}_{key}"
        )
        assert sensor_id is not None
        assert hass.states.get(sensor_id).state == "unavailable"

        if outcome == "unload_offline":
            assert await hass.config_entries.async_unload(entry.entry_id)
            assert await hass.config_entries.async_setup(entry.entry_id)
            assert entry.state is ConfigEntryState.LOADED
            assert hass.states.get(sensor_id).state == "unavailable"
            assert await hass.config_entries.async_unload(entry.entry_id)
            return

        real.return_value = RealDataNew_pb2.RealDataNewReqDTO(
            device_serial_number=serial, dtu_daily_energy=42
        )
        app_info.return_value = APPInfomationData_pb2.APPInfoDataReqDTO(
            dtu_serial_number=serial
        )
        app_info.return_value.dtu_info.signal_strength = 50
        config.return_value = GetConfig_pb2.GetConfigReqDTO(wifi_ssid="test-wifi")
        storage.return_value = ESData_pb2.ESDataReqDTO()
        storage.return_value.production.energy_to_load = 100
        mode.return_value = ESParaSet_pb2.ESParaSetBO()
        mode.return_value.emspara.mode = 1
        mode.return_value.emspara.selfu.rev_soc = 10
        if outcome == "unsupported_config":
            config.return_value = None
            mode.return_value = None
        freezer.tick(timedelta(seconds=36))
        async_fire_time_changed(hass, dt_util.utcnow())
        await hass.async_block_till_done(wait_background_tasks=True)
        assert entry.state is ConfigEntryState.LOADED
        assert live.last_update_success
        assert metadata.last_update_success == (outcome == "recover")
        expected_interval = (
            timedelta(minutes=5) if hybrid or outcome == "recover" else None
        )
        assert metadata.update_interval == expected_interval
        expected_state = (
            ("self_use" if outcome == "recover" else "unavailable") if hybrid else "42"
        )
        assert hass.states.get(sensor_id).state == expected_state
        if not hybrid:
            assert runtime[HASS_APP_INFO_COORDINATOR].last_update_success
        metadata_calls = mode.await_count if hybrid else config.await_count
        assert metadata_calls == 2
        freezer.tick(timedelta(seconds=36))
        async_fire_time_changed(hass, dt_util.utcnow())
        await hass.async_block_till_done(wait_background_tasks=True)
        assert (mode.await_count if hybrid else config.await_count) == metadata_calls
        assert await hass.config_entries.async_unload(entry.entry_id)


async def test_offline_startup_does_not_trust_another_entry_device(hass):
    """A registered DTU from another entry is not proof this entry was set up."""
    serial = "4143A6B7C8D9"
    owner = MockConfigEntry(domain="other_integration")
    owner.add_to_hass(hass)
    dr.async_get(hass).async_get_or_create(
        config_entry_id=owner.entry_id, identifiers={(DOMAIN, serial)}
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=CONFIG_VERSION,
        data={
            CONF_HOST: "dtu.local",
            CONF_DTU_SERIAL_NUMBER: serial,
            CONF_UPDATE_INTERVAL: 35,
            CONF_INVERTERS: ["1124A6B7C8D9"],
        },
    )
    entry.add_to_hass(hass)
    with (
        patch.object(DTU, "async_app_information_data", return_value=None),
        patch.object(DTU, "async_get_real_data_new", return_value=None),
        patch.object(hass.config_entries, "async_forward_entry_setups") as forward,
    ):
        assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_RETRY
    forward.assert_not_awaited()
