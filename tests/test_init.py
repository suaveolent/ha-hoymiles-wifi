"""Test component setup."""

from datetime import timedelta
from unittest.mock import patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_HOST
from homeassistant.helpers import device_registry as dr
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from hoymiles_wifi.dtu import DTU
from hoymiles_wifi.protobuf import APPInfomationData_pb2, GetConfig_pb2, RealDataNew_pb2
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
    CONF_UPDATE_INTERVAL,
    CONFIG_VERSION,
    DOMAIN,
    HASS_CONFIG_COORDINATOR,
    HASS_DATA_COORDINATOR,
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
        patch.object(DTU, "async_get_config", return_value=config) as get_config,
        patch.object(
            DTU, "async_get_energy_storage_data", return_value=hybrid
        ) as get_hybrid,
        patch.object(
            hass.config_entries,
            "async_forward_entry_setups",
            side_effect=forward_platforms,
        ) as forward,
        patch.object(hass.config_entries, "async_unload_platforms", return_value=True),
    ):
        failed_fetch = {
            "real_data": get_real,
            "config": get_config,
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


async def test_setup_succeeds_when_dtu_never_answers_get_config(hass):
    """DTUs that ignore GetConfig must still load; config entities stay unknown."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=CONFIG_VERSION,
        data={
            CONF_HOST: "dtu.local",
            CONF_DTU_SERIAL_NUMBER: "414392349724",
            CONF_UPDATE_INTERVAL: 35,
            CONF_INVERTERS: ["112345678901"],
        },
    )
    entry.add_to_hass(hass)
    app_info = APPInfomationData_pb2.APPInfoDataReqDTO()
    real_data = RealDataNew_pb2.RealDataNewReqDTO(device_serial_number="414392349724")

    with (
        patch.object(DTU, "async_app_information_data", return_value=app_info),
        patch.object(DTU, "async_get_real_data_new", return_value=real_data),
        patch.object(DTU, "async_get_config", return_value=None),
        patch.object(
            hass.config_entries, "async_forward_entry_setups", return_value=None
        ) as forward,
        patch.object(hass.config_entries, "async_unload_platforms", return_value=True),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        assert entry.state is ConfigEntryState.LOADED
        forward.assert_awaited_once()
        runtime = hass.data[DOMAIN][entry.entry_id]
        assert runtime[HASS_DATA_COORDINATOR].data is real_data
        assert runtime[HASS_CONFIG_COORDINATOR].data is None
        assert await hass.config_entries.async_unload(entry.entry_id)
