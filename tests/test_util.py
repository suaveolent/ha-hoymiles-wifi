"""Tests for DTU encryption updates."""

from hoymiles_wifi.dtu import DTU
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hoymiles_wifi.const import CONF_ENC_RAND, DOMAIN
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
