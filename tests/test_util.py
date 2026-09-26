"""Tests for DTU encryption updates."""

from unittest.mock import patch

import pytest
from hoymiles_wifi.dtu import DTU
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hoymiles_wifi.const import CONF_ENC_RAND, CONF_IS_ENCRYPTED, DOMAIN
from custom_components.hoymiles_wifi.util import async_check_and_update_enc_rand


async def test_update_enc_rand(hass):
    """Update the entry using Home Assistant's synchronous callback."""
    entry = MockConfigEntry(domain=DOMAIN, data={"host": "dtu.local"})
    entry.add_to_hass(hass)
    dtu = DTU("dtu.local")
    enc_rand = "f5480938516c557e347bc49c672b6af1"

    await async_check_and_update_enc_rand(hass, entry, dtu, enc_rand)

    assert entry.data[CONF_ENC_RAND] == enc_rand
    assert entry.data["host"] == "dtu.local"
    assert dtu.enc_rand == bytes.fromhex(enc_rand)
    assert entry.data[CONF_IS_ENCRYPTED] is True
    assert dtu.is_encrypted is True


@pytest.mark.parametrize("stored_flag", [None, False, True])
@pytest.mark.parametrize("stored_rand", ["00" * 16, "f5480938516c557e347bc49c672b6af1"])
async def test_repair_encryption_state(hass, stored_flag, stored_rand):
    """Repair runtime and persisted state, including an unchanged random value."""
    enc_rand = "f5480938516c557e347bc49c672b6af1"
    data = {"host": "dtu.local", CONF_ENC_RAND: stored_rand}
    if stored_flag is not None:
        data[CONF_IS_ENCRYPTED] = stored_flag
    entry = MockConfigEntry(domain=DOMAIN, data=data)
    entry.add_to_hass(hass)
    dtu = DTU("dtu.local")

    with patch.object(
        hass.config_entries,
        "async_update_entry",
        wraps=hass.config_entries.async_update_entry,
    ) as update_entry:
        await async_check_and_update_enc_rand(hass, entry, dtu, enc_rand)

        assert dtu.is_encrypted is True
        assert dtu.enc_rand == bytes.fromhex(enc_rand)
        assert entry.data == {
            "host": "dtu.local",
            CONF_IS_ENCRYPTED: True,
            CONF_ENC_RAND: enc_rand,
        }
        assert update_entry.call_count == int(
            stored_flag is not True or stored_rand != enc_rand
        )

        update_entry.reset_mock()
        await async_check_and_update_enc_rand(hass, entry, dtu, enc_rand)
        update_entry.assert_not_called()


async def test_rotate_enc_rand(hass):
    """An already encrypted DTU adopts a new random value without a reload."""
    old_rand = "00" * 16
    new_rand = "f5480938516c557e347bc49c672b6af1"
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_IS_ENCRYPTED: True, CONF_ENC_RAND: old_rand},
    )
    entry.add_to_hass(hass)
    dtu = DTU("dtu.local", is_encrypted=True, enc_rand=bytes.fromhex(old_rand))

    await async_check_and_update_enc_rand(hass, entry, dtu, new_rand)

    assert dtu.is_encrypted is True
    assert dtu.enc_rand == bytes.fromhex(new_rand)
    assert entry.data[CONF_IS_ENCRYPTED] is True
    assert entry.data[CONF_ENC_RAND] == new_rand
