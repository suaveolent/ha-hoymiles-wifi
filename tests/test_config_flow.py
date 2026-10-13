"""Unit tests for the Hoymiles config flow."""

from unittest.mock import patch

from homeassistant import config_entries
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import translation
from hoymiles_wifi.protobuf import APPInfomationData_pb2, RealDataNew_pb2
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hoymiles_wifi.const import (
    CONF_CLOUD_PAUSE,
    CONF_DTU_SERIAL_NUMBER,
    CONF_ENC_RAND,
    CONF_HYBRID_INVERTERS,
    CONF_INVERTERS,
    CONF_IS_ENCRYPTED,
    CONF_METERS,
    CONF_PORTS,
    CONF_THREE_PHASE_INVERTERS,
    CONF_TIMEOUT,
    CONF_UPDATE_INTERVAL,
    CONFIG_VERSION,
    DEFAULT_TIMEOUT_SECONDS,
    DEFAULT_UPDATE_INTERVAL_SECONDS,
    DOMAIN,
)
from custom_components.hoymiles_wifi.error import CannotConnect

DTU_TEST_HOST = "DTUBI-123456789101.lan"

DTU_TEST_SERIAL_NUMBER = "414312345678"

MOCK_DATA_STEP = {
    CONF_HOST: DTU_TEST_HOST,
    CONF_UPDATE_INTERVAL: DEFAULT_UPDATE_INTERVAL_SECONDS,
}

MOCK_DATA_RESULT = {
    CONF_CLOUD_PAUSE: 0,
    CONF_HOST: DTU_TEST_HOST,
    CONF_DTU_SERIAL_NUMBER: DTU_TEST_SERIAL_NUMBER,
    CONF_UPDATE_INTERVAL: DEFAULT_UPDATE_INTERVAL_SECONDS,
    CONF_INVERTERS: [],
    CONF_PORTS: [],
    CONF_THREE_PHASE_INVERTERS: [],
    CONF_METERS: [],
    CONF_HYBRID_INVERTERS: [],
    CONF_IS_ENCRYPTED: False,
    CONF_ENC_RAND: "",
    CONF_TIMEOUT: DEFAULT_TIMEOUT_SECONDS,
}


MOCK_DATA_REAL_DATA_NEW = RealDataNew_pb2.RealDataNewReqDTO()
MOCK_DATA_REAL_DATA_NEW.device_serial_number = DTU_TEST_SERIAL_NUMBER


@pytest.fixture(autouse=True)
def mock_app_information_data():
    """Use a plaintext DTU response without contacting a real device."""
    response = APPInfomationData_pb2.APPInfoDataReqDTO()
    response.dtu_info.dfs = 0
    with patch(
        "hoymiles_wifi.dtu.DTU.async_app_information_data",
        return_value=response,
    ):
        yield


@pytest.mark.parametrize("cloud_pause", [0, 1, 30, 120])
async def test_form_valid_input(hass: HomeAssistant, cloud_pause) -> None:
    """Test handling valid user input."""

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {}

    with (
        patch(
            "custom_components.hoymiles_wifi.async_setup_entry",
            return_value=True,
        ) as mock_setup_entry,
        patch(
            "hoymiles_wifi.dtu.DTU.async_get_real_data_new",
            return_value=MOCK_DATA_REAL_DATA_NEW,
        ) as mock_async_get_real_data_new,
    ):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                **MOCK_DATA_STEP,
                CONF_CLOUD_PAUSE: cloud_pause,
            },
        )
        await hass.async_block_till_done()

    assert result2["type"] == FlowResultType.CREATE_ENTRY
    assert result2["title"] == MOCK_DATA_STEP[CONF_HOST]
    assert result2["data"] == {
        **MOCK_DATA_RESULT,
        CONF_CLOUD_PAUSE: cloud_pause,
    }
    assert len(mock_setup_entry.mock_calls) == 1
    assert len(mock_async_get_real_data_new.mock_calls) == 1


@pytest.mark.parametrize(
    ("raise_error", "text_error"),
    [
        (CannotConnect("Test hoymiles exception"), "cannot_connect"),
    ],
)
async def test_flow_user_init_data_error_and_recover(
    hass: HomeAssistant, raise_error, text_error
) -> None:
    """Test exceptions and recovery."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {}

    with patch(
        "custom_components.hoymiles_wifi.util.DTU.async_get_real_data_new",
        side_effect=raise_error,
    ) as mock_async_get_config_entry_data_for_host:
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            MOCK_DATA_STEP,
        )
        await hass.async_block_till_done()

    assert result2["type"] == FlowResultType.FORM
    assert result2["errors"] == {"base": text_error}

    assert len(mock_async_get_config_entry_data_for_host.mock_calls) == 1

    # Recover
    with (
        patch(
            "custom_components.hoymiles_wifi.async_setup_entry",
            return_value=True,
        ) as mock_setup_entry,
        patch(
            "hoymiles_wifi.dtu.DTU.async_get_real_data_new",
            return_value=MOCK_DATA_REAL_DATA_NEW,
        ) as mock_async_get_real_data_new,
    ):
        result3 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            MOCK_DATA_STEP,
        )

        await hass.async_block_till_done()

    assert result3["type"] == FlowResultType.CREATE_ENTRY
    assert result3["title"] == MOCK_DATA_STEP[CONF_HOST]
    assert result3["data"] == MOCK_DATA_RESULT
    assert len(mock_setup_entry.mock_calls) == 1
    assert len(mock_async_get_real_data_new.mock_calls) == 1


@pytest.mark.parametrize("unique_id", [None, DTU_TEST_SERIAL_NUMBER])
@pytest.mark.parametrize("custom_title", [False, True])
async def test_reconfigure_updates_existing_entry(hass, unique_id, custom_title):
    """Host changes persist for legacy entries and retain unrelated settings."""
    old_host = "192.168.1.10"
    new_host = "192.168.1.20"
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=CONFIG_VERSION,
        unique_id=unique_id,
        title="Garden DTU" if custom_title else old_host,
        data={
            **MOCK_DATA_RESULT,
            CONF_HOST: old_host,
            CONF_UPDATE_INTERVAL: 77,
            CONF_TIMEOUT: 21,
            CONF_CLOUD_PAUSE: 30,
            "preserved_setting": True,
        },
    )
    entry.add_to_hass(hass)
    entry_id = entry.entry_id
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_RECONFIGURE, "entry_id": entry_id},
    )
    assert result["type"] is FlowResultType.FORM
    with (
        patch(
            "hoymiles_wifi.dtu.DTU.async_get_real_data_new",
            return_value=MOCK_DATA_REAL_DATA_NEW,
        ),
        patch.object(hass.config_entries, "async_reload", return_value=False) as reload,
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_HOST: new_host}
        )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.entry_id == entry_id
    assert entry.unique_id == DTU_TEST_SERIAL_NUMBER
    assert entry.data == {
        **MOCK_DATA_RESULT,
        CONF_HOST: new_host,
        CONF_UPDATE_INTERVAL: 77,
        CONF_TIMEOUT: 21,
        CONF_CLOUD_PAUSE: 30,
        "preserved_setting": True,
    }
    assert entry.title == ("Garden DTU" if custom_title else new_host)
    assert hass.config_entries.async_entries(DOMAIN) == [entry]
    reload.assert_awaited_once_with(entry_id)


@pytest.mark.parametrize("unique_id", [None, DTU_TEST_SERIAL_NUMBER])
async def test_reconfigure_rejects_another_device(hass, unique_id):
    """A reachable address must still identify the originally configured DTU."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=CONFIG_VERSION,
        unique_id=unique_id,
        data=MOCK_DATA_RESULT,
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_RECONFIGURE,
            "entry_id": entry.entry_id,
        },
    )
    other = RealDataNew_pb2.RealDataNewReqDTO(device_serial_number="414399999999")
    with (
        patch("hoymiles_wifi.dtu.DTU.async_get_real_data_new", return_value=other),
        patch.object(hass.config_entries, "async_reload") as reload,
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_HOST: "another.local"}
        )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "another_device"
    assert entry.data == MOCK_DATA_RESULT
    reload.assert_not_awaited()


async def test_reconfigure_connection_failure_keeps_configuration(hass):
    """An unreachable replacement address leaves the form open and entry unchanged."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=CONFIG_VERSION,
        unique_id=DTU_TEST_SERIAL_NUMBER,
        data=MOCK_DATA_RESULT,
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_RECONFIGURE,
            "entry_id": entry.entry_id,
        },
    )
    with (
        patch(
            "custom_components.hoymiles_wifi.config_flow.async_get_config_entry_data_for_host",
            side_effect=CannotConnect,
        ),
        patch.object(hass.config_entries, "async_reload") as reload,
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_HOST: "unreachable.local"}
        )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}
    assert entry.data == MOCK_DATA_RESULT
    reload.assert_not_awaited()


@pytest.mark.parametrize("language", ["en", "de", "fr"])
async def test_reconfigure_abort_messages_are_localized(hass, language):
    """Home Assistant resolves both reconfiguration outcomes to translated messages."""
    translations = await translation.async_get_translations(
        hass, language, "config", {DOMAIN}
    )
    for reason in ("another_device", "reconfigure_successful"):
        message = translations[f"component.{DOMAIN}.config.abort.{reason}"]
        assert message
        assert message != reason
