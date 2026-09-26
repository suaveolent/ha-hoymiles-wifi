"""Tests for Hoymiles device relationships."""

import pytest
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hoymiles_wifi.const import CONF_DTU_SERIAL_NUMBER, DOMAIN
from custom_components.hoymiles_wifi.entity import (
    HoymilesEntity,
    HoymilesEntityDescription,
)


@pytest.mark.parametrize(
    ("key", "serial_number", "is_dtu"),
    [
        ("dtu_power", "4143A01B0514", True),
        ("sgs_data_power", "112345678901", False),
        ("meter_power", "123456789012", False),
    ],
)
async def test_device_parent(hass, caplog, key, serial_number, is_dtu):
    """Resolve the owning entry's DTU without deprecated registry parameters."""
    registry = dr.async_get(hass)
    dtu_serial_number = "4143A01B0514"
    parents = []
    entries = []
    # Identical identifiers in different entries must not pick the wrong parent.
    for _ in range(2):
        entry = MockConfigEntry(
            domain=DOMAIN, data={CONF_DTU_SERIAL_NUMBER: dtu_serial_number}
        )
        entry.add_to_hass(hass)
        entries.append(entry)
        parents.append(
            registry.async_get_or_create(
                config_entry_id=entry.entry_id,
                identifiers={(DOMAIN, dtu_serial_number)},
            )
        )

    entity = HoymilesEntity(
        entries[1],
        HoymilesEntityDescription(
            key=key, serial_number=serial_number, is_dtu_sensor=is_dtu
        ),
    )
    entity.hass = hass
    info = entity.device_info
    assert "via_device" not in info
    if is_dtu:
        assert "via_device_id" not in info
    else:
        assert info["via_device_id"] == parents[1].id
        assert info["via_device_id"] != parents[0].id

    device = registry.async_get_or_create(
        config_entry_id=entries[1].entry_id, **info
    )
    assert device.via_device_id == (None if is_dtu else parents[1].id)
    assert device.identifiers == {(DOMAIN, serial_number)}
    assert "deprecated" not in caplog.text


def test_device_parent_legacy_api(hass, monkeypatch):
    """Keep device links working when the new registry helper is unavailable."""
    monkeypatch.delattr(dr, "async_get_device_id_by_identifier")
    entry = MockConfigEntry(
        domain=DOMAIN, data={CONF_DTU_SERIAL_NUMBER: "4143A01B0514"}
    )
    entity = HoymilesEntity(
        entry,
        HoymilesEntityDescription(
            key="sgs_data_power", serial_number="112345678901"
        ),
    )
    entity.hass = hass

    assert entity.device_info["via_device"] == (DOMAIN, "4143A01B0514")
    assert "via_device_id" not in entity.device_info
