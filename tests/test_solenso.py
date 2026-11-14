"""Verify DTUs with alphanumeric serials can load all integration platforms."""

from unittest.mock import Mock, patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_HOST
from homeassistant.helpers import device_registry as dr, entity_registry as er
from hoymiles_wifi.dtu import DTU
from hoymiles_wifi.protobuf import APPInfomationData_pb2, GetConfig_pb2, RealDataNew_pb2
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hoymiles_wifi.const import (
    CONF_DTU_SERIAL_NUMBER,
    CONF_INVERTERS,
    CONF_PORTS,
    CONF_UPDATE_INTERVAL,
    CONFIG_VERSION,
    DOMAIN,
)
from custom_components.hoymiles_wifi.sensor import (
    HOYMILES_SENSORS,
    get_sensors_for_description,
)


@pytest.mark.parametrize(
    ("serial", "model"),
    [
        ("D010987ZX", "Solenso SLT-V2"),
        ("4143A6B7C8D9J", "DTUBI"),
        ("FFFF987ZX", "Unknown"),
        ("ZZZZ987ZX", "Unknown"),
        ("41", "Unknown"),
    ],
)
async def test_alphanumeric_dtu_setup(hass, serial, model):
    """Load real platforms and preserve DTU measurements despite unusual serials."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=CONFIG_VERSION,
        data={
            CONF_HOST: "dtu.local",
            CONF_DTU_SERIAL_NUMBER: serial,
            CONF_UPDATE_INTERVAL: 35,
            CONF_INVERTERS: ["1144A6B7C8D9"],
            CONF_PORTS: [],
        },
    )
    entry.add_to_hass(hass)
    response = RealDataNew_pb2.RealDataNewReqDTO(
        device_serial_number=serial, dtu_power=2500, dtu_daily_energy=174
    )
    with (
        patch.object(
            DTU,
            "async_app_information_data",
            return_value=APPInfomationData_pb2.APPInfoDataReqDTO(),
        ),
        patch.object(DTU, "async_get_real_data_new", return_value=response),
        patch.object(
            DTU, "async_get_config", return_value=GetConfig_pb2.GetConfigReqDTO()
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert entry.state is ConfigEntryState.LOADED
        registry = er.async_get(hass)
        entities = er.async_entries_for_config_entry(registry, entry.entry_id)
        assert {entity.domain for entity in entities} >= {
            "sensor",
            "button",
            "number",
            "binary_sensor",
        }
        for key, value in (("dtu_power", "250.0"), ("dtu_daily_energy", "174")):
            entity_id = registry.async_get_entity_id(
                "sensor", DOMAIN, f"hoymiles_{entry.entry_id}_{key}"
            )
            assert entity_id is not None
            assert hass.states.get(entity_id).state == value
        device = dr.async_get(hass).async_get_device_by_identifier(
            (DOMAIN, serial), entry.entry_id
        )
        assert device is not None
        assert device.model == model
        assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize("key", ["dtu_power", "dtu_daily_energy"])
def test_known_unsupported_dtu_keeps_sensor_filter(key):
    """An unidentified DTU fallback must not bypass a recognized type's restrictions."""
    description = next(item for item in HOYMILES_SENSORS if item.key == key)
    factory = Mock()
    sensors = get_sensors_for_description(
        None, description, None, factory, "D030A6B7C8D9", [], []
    )
    assert sensors == []
    factory.assert_not_called()
