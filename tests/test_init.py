"""Test component setup."""

from unittest.mock import patch

import pytest
from homeassistant.const import CONF_HOST
from homeassistant.setup import async_setup_component
from hoymiles_wifi.dtu import DTU
from hoymiles_wifi.protobuf import APPInfomationData_pb2, GetConfig_pb2, RealDataNew_pb2
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hoymiles_wifi.const import (
    CONF_ENC_RAND,
    CONF_INVERTERS,
    CONF_IS_ENCRYPTED,
    CONF_UPDATE_INTERVAL,
    CONFIG_VERSION,
    DOMAIN,
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
            CONF_UPDATE_INTERVAL: 35,
            CONF_INVERTERS: ["112345678901"],
            CONF_IS_ENCRYPTED: False,
            CONF_ENC_RAND: enc_rand,
        },
    )
    entry.add_to_hass(hass)
    requests = []
    app_info_modes = []

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
        patch.object(DTU, "async_app_information_data", autospec=True, side_effect=app_info),
        patch.object(DTU, "async_get_real_data_new", autospec=True, side_effect=real_data),
        patch.object(DTU, "async_get_config", autospec=True, side_effect=config_data),
        patch.object(hass.config_entries, "async_forward_entry_setups"),
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

        assert await hass.config_entries.async_unload(entry.entry_id)
