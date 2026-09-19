"""Tests for DTU encryption state detection and recovery.

Covers the failure this fixes: a DTU that switches to the encrypted protocol
after a firmware update, where app info requests keep working (they are never
encrypted) but every real data request silently fails to parse.
"""

from unittest.mock import patch

from homeassistant.core import HomeAssistant
from hoymiles_wifi.dtu import NetworkState
from hoymiles_wifi.protobuf.APPInfomationData_pb2 import APPDtuInfoMO
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hoymiles_wifi import _decode_stored_enc_rand
from custom_components.hoymiles_wifi.const import (
    CONF_ENC_RAND,
    CONF_IS_ENCRYPTED,
    DOMAIN,
    ENCRYPTION_RESYNC_MIN_INTERVAL_SECONDS,
)
from custom_components.hoymiles_wifi.coordinator import (
    HoymilesAppInfoUpdateCoordinator,
    HoymilesRealDataUpdateCoordinator,
)
from custom_components.hoymiles_wifi.util import async_sync_encryption_state

# Measured on real hardware running the firmware that enables encryption.
DFS_ENCRYPTED = 1308623040
# Same value with the encryption bit (25) cleared, i.e. old firmware.
DFS_PLAINTEXT = DFS_ENCRYPTED & ~(1 << 25)

RAND = bytes.fromhex("f5480938516c557e347bc49c672b6af1")
ROTATED_RAND = bytes.fromhex("00112233445566778899aabbccddeeff")


def make_dtu_info(dfs: int, enc_rand: bytes = b"") -> APPDtuInfoMO:
    """Build a real APPDtuInfoMO, as returned by the app info request."""
    info = APPDtuInfoMO()
    info.dfs = dfs
    info.enc_rand = enc_rand
    return info


class FakeDTU:
    """Minimal stand-in for the library's DTU.

    Only models what the encryption path touches: the two mutable encryption
    attributes, the network state, and the two requests involved.
    """

    def __init__(self, is_encrypted: bool = False, enc_rand: bytes = b""):
        """Initialize the fake."""
        self.is_encrypted = is_encrypted
        self.enc_rand = enc_rand
        self.state = NetworkState.Unknown
        self.real_data_responses: list[object] = []
        self.app_info_response: object = None
        self.real_data_calls = 0
        self.app_info_calls = 0

    def get_state(self) -> NetworkState:
        """Return the current network state."""
        return self.state

    async def async_get_real_data_new(self):
        """Pop the next scripted real data response."""
        self.real_data_calls += 1
        if not self.real_data_responses:
            return None
        return self.real_data_responses.pop(0)

    async def async_app_information_data(self):
        """Return the scripted app info response."""
        self.app_info_calls += 1
        return self.app_info_response


async def add_entry(hass: HomeAssistant, data: dict) -> MockConfigEntry:
    """Add a config entry carrying the given data."""
    entry = MockConfigEntry(domain=DOMAIN, data=data)
    entry.add_to_hass(hass)
    return entry


# --------------------------------------------------------------------------
# async_sync_encryption_state
# --------------------------------------------------------------------------


async def test_detects_firmware_switch_to_encrypted(hass: HomeAssistant) -> None:
    """The reported bug: entry says plaintext, DTU now expects encryption."""
    entry = await add_entry(hass, {CONF_IS_ENCRYPTED: False, CONF_ENC_RAND: ""})
    dtu = FakeDTU()

    async_sync_encryption_state(
        hass, entry, dtu, make_dtu_info(DFS_ENCRYPTED, RAND)
    )

    assert dtu.is_encrypted is True
    assert dtu.enc_rand == RAND
    # Persisted, so the next setup does not rebuild a plaintext DTU.
    assert entry.data[CONF_IS_ENCRYPTED] is True
    assert entry.data[CONF_ENC_RAND] == RAND.hex()


async def test_legacy_entry_without_encryption_keys(hass: HomeAssistant) -> None:
    """An entry predating encryption support has neither key."""
    entry = await add_entry(hass, {"host": "1.2.3.4"})
    dtu = FakeDTU()

    async_sync_encryption_state(hass, entry, dtu, make_dtu_info(DFS_PLAINTEXT))

    assert dtu.is_encrypted is False
    # Nothing changed, so nothing should have been written.
    assert CONF_IS_ENCRYPTED not in entry.data


@pytest.mark.parametrize(
    ("stored", "dtu_kwargs", "dtu_info"),
    [
        (
            {CONF_IS_ENCRYPTED: False, CONF_ENC_RAND: ""},
            {},
            (DFS_PLAINTEXT, b""),
        ),
        (
            {CONF_IS_ENCRYPTED: True, CONF_ENC_RAND: RAND.hex()},
            {"is_encrypted": True, "enc_rand": RAND},
            (DFS_ENCRYPTED, RAND),
        ),
    ],
    ids=["plaintext", "encrypted"],
)
async def test_steady_state_does_not_write(
    hass: HomeAssistant, stored, dtu_kwargs, dtu_info
) -> None:
    """When nothing changed, the config entry must be left alone."""
    entry = await add_entry(hass, stored)
    dtu = FakeDTU(**dtu_kwargs)

    with patch.object(
        hass.config_entries, "async_update_entry", wraps=hass.config_entries.async_update_entry
    ) as update:
        async_sync_encryption_state(hass, entry, dtu, make_dtu_info(*dtu_info))

    assert update.call_count == 0


async def test_enc_rand_rotation(hass: HomeAssistant) -> None:
    """A DTU reboot can rotate the encryption random."""
    entry = await add_entry(
        hass, {CONF_IS_ENCRYPTED: True, CONF_ENC_RAND: RAND.hex()}
    )
    dtu = FakeDTU(is_encrypted=True, enc_rand=RAND)

    async_sync_encryption_state(
        hass, entry, dtu, make_dtu_info(DFS_ENCRYPTED, ROTATED_RAND)
    )

    assert dtu.enc_rand == ROTATED_RAND
    assert entry.data[CONF_ENC_RAND] == ROTATED_RAND.hex()


@pytest.mark.parametrize("dfs", [DFS_PLAINTEXT, 0], ids=["flags_set", "dfs_zero"])
async def test_firmware_downgrade_turns_encryption_off(
    hass: HomeAssistant, dfs: int
) -> None:
    """Encryption must be able to go back off, including when dfs is zero.

    dfs == 0 is the regression guard: the app info coordinator used to skip the
    sync entirely for a falsy dfs, which made the downgrade path unreachable.
    """
    entry = await add_entry(
        hass, {CONF_IS_ENCRYPTED: True, CONF_ENC_RAND: RAND.hex()}
    )
    dtu = FakeDTU(is_encrypted=True, enc_rand=RAND)

    async_sync_encryption_state(hass, entry, dtu, make_dtu_info(dfs))

    assert dtu.is_encrypted is False
    assert dtu.enc_rand == b""
    assert entry.data[CONF_IS_ENCRYPTED] is False
    assert entry.data[CONF_ENC_RAND] == ""


@pytest.mark.parametrize(
    "bad_rand",
    [b"", b"\x01\x02\x03"],
    ids=["empty", "too_short"],
)
async def test_encryption_bit_without_usable_rand(
    hass: HomeAssistant, bad_rand: bytes
) -> None:
    """A set bit with an unusable key must not enable encryption.

    The cipher asserts on a 16 byte key from outside the library's error
    handling, so enabling encryption here would raise on every request.
    """
    entry = await add_entry(hass, {CONF_IS_ENCRYPTED: False, CONF_ENC_RAND: ""})
    dtu = FakeDTU()

    async_sync_encryption_state(
        hass, entry, dtu, make_dtu_info(DFS_ENCRYPTED, bad_rand)
    )

    assert dtu.is_encrypted is False
    assert dtu.enc_rand == b""
    # Must not persist the impossible "encrypted but no key" combination.
    assert entry.data[CONF_IS_ENCRYPTED] is False
    assert entry.data[CONF_ENC_RAND] == ""


# --------------------------------------------------------------------------
# _decode_stored_enc_rand
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("is_encrypted", "stored", "expected"),
    [
        (False, "", None),
        (False, RAND.hex(), None),
        (True, RAND.hex(), RAND),
        (True, None, None),
        (True, "", None),
        (True, "not hex at all", None),
        (True, "abc", None),
        (True, "aabb", None),
    ],
    ids=[
        "plaintext",
        "plaintext_with_stale_rand",
        "valid",
        "missing",
        "empty",
        "not_hex",
        "odd_length",
        "too_short",
    ],
)
def test_decode_stored_enc_rand(is_encrypted, stored, expected) -> None:
    """Only a well-formed 16 byte key may be used to build an encrypted DTU."""
    assert _decode_stored_enc_rand("1.2.3.4", is_encrypted, stored) == expected


# --------------------------------------------------------------------------
# Real data coordinator self-heal
# --------------------------------------------------------------------------


async def make_coordinator(
    hass: HomeAssistant, dtu: FakeDTU, data: dict
) -> HoymilesRealDataUpdateCoordinator:
    """Build a real data coordinator around the fake DTU."""
    entry = await add_entry(hass, data)
    return HoymilesRealDataUpdateCoordinator(
        hass, dtu=dtu, config_entry=entry, update_interval=None
    )


async def test_self_heal_recovers_after_encryption_switch(
    hass: HomeAssistant,
) -> None:
    """Unparseable payload plus a changed encryption state retries and recovers."""
    dtu = FakeDTU()
    dtu.state = NetworkState.Unknown
    dtu.real_data_responses = [None, "real data"]
    dtu.app_info_response = type(
        "R", (), {"dtu_info": make_dtu_info(DFS_ENCRYPTED, RAND)}
    )()

    coordinator = await make_coordinator(
        hass, dtu, {CONF_IS_ENCRYPTED: False, CONF_ENC_RAND: ""}
    )
    result = await coordinator._async_update_data()

    assert result == "real data"
    assert dtu.is_encrypted is True
    assert dtu.app_info_calls == 1
    assert dtu.real_data_calls == 2


async def test_no_probe_when_offline(hass: HomeAssistant) -> None:
    """An unreachable DTU must not pay an extra app info request."""
    dtu = FakeDTU()
    dtu.state = NetworkState.Offline

    coordinator = await make_coordinator(hass, dtu, {CONF_IS_ENCRYPTED: False})
    assert await coordinator._async_update_data() is None

    assert dtu.app_info_calls == 0
    assert dtu.real_data_calls == 1


async def test_no_probe_when_online_with_empty_payload(hass: HomeAssistant) -> None:
    """A parsed but empty response leaves the DTU Online, which is not an
    encryption problem and must not trigger a probe."""
    dtu = FakeDTU()
    dtu.state = NetworkState.Online

    coordinator = await make_coordinator(hass, dtu, {CONF_IS_ENCRYPTED: False})
    assert await coordinator._async_update_data() is None

    assert dtu.app_info_calls == 0
    assert dtu.real_data_calls == 1


async def test_no_retry_when_encryption_state_unchanged(
    hass: HomeAssistant,
) -> None:
    """If the probe finds nothing new, retrying the same request is pointless."""
    dtu = FakeDTU()
    dtu.state = NetworkState.Unknown
    dtu.app_info_response = type(
        "R", (), {"dtu_info": make_dtu_info(DFS_PLAINTEXT)}
    )()

    coordinator = await make_coordinator(hass, dtu, {CONF_IS_ENCRYPTED: False})
    assert await coordinator._async_update_data() is None

    assert dtu.app_info_calls == 1
    assert dtu.real_data_calls == 1


async def test_app_info_unavailable_during_probe(hass: HomeAssistant) -> None:
    """The probe itself can fail. That must not raise."""
    dtu = FakeDTU()
    dtu.state = NetworkState.Unknown
    dtu.app_info_response = None

    coordinator = await make_coordinator(hass, dtu, {CONF_IS_ENCRYPTED: False})
    assert await coordinator._async_update_data() is None

    assert dtu.app_info_calls == 1
    assert dtu.real_data_calls == 1


async def test_probe_is_throttled(hass: HomeAssistant) -> None:
    """A payload unparseable for a non-encryption reason must not add an app
    info request to every single poll."""
    dtu = FakeDTU()
    dtu.state = NetworkState.Unknown
    dtu.app_info_response = type(
        "R", (), {"dtu_info": make_dtu_info(DFS_PLAINTEXT)}
    )()

    coordinator = await make_coordinator(hass, dtu, {CONF_IS_ENCRYPTED: False})

    with patch(
        "custom_components.hoymiles_wifi.coordinator.time.monotonic",
        side_effect=[0.0, 1.0, 2.0],
    ):
        await coordinator._async_update_data()
        await coordinator._async_update_data()
        await coordinator._async_update_data()

    assert dtu.real_data_calls == 3
    assert dtu.app_info_calls == 1


async def test_probe_resumes_after_throttle_window(hass: HomeAssistant) -> None:
    """Once the window has passed, probing resumes."""
    dtu = FakeDTU()
    dtu.state = NetworkState.Unknown
    dtu.app_info_response = type(
        "R", (), {"dtu_info": make_dtu_info(DFS_PLAINTEXT)}
    )()

    coordinator = await make_coordinator(hass, dtu, {CONF_IS_ENCRYPTED: False})

    with patch(
        "custom_components.hoymiles_wifi.coordinator.time.monotonic",
        side_effect=[0.0, ENCRYPTION_RESYNC_MIN_INTERVAL_SECONDS + 1.0],
    ):
        await coordinator._async_update_data()
        await coordinator._async_update_data()

    assert dtu.app_info_calls == 2


# --------------------------------------------------------------------------
# App info coordinator
#
# These go through the coordinator rather than calling the sync helper
# directly, so they exercise the guard in front of it.
# --------------------------------------------------------------------------


async def make_app_info_coordinator(
    hass: HomeAssistant, dtu: FakeDTU, data: dict
) -> tuple[HoymilesAppInfoUpdateCoordinator, MockConfigEntry]:
    """Build an app info coordinator around the fake DTU."""
    entry = await add_entry(hass, data)
    coordinator = HoymilesAppInfoUpdateCoordinator(
        hass=hass, dtu=dtu, config_entry=entry, update_interval=None
    )
    return coordinator, entry


async def test_app_info_detects_encryption_switch(hass: HomeAssistant) -> None:
    """App info keeps working after the switch, so it is what detects it."""
    dtu = FakeDTU()
    response = type("R", (), {"dtu_info": make_dtu_info(DFS_ENCRYPTED, RAND)})()
    dtu.app_info_response = response

    coordinator, entry = await make_app_info_coordinator(
        hass, dtu, {CONF_IS_ENCRYPTED: False, CONF_ENC_RAND: ""}
    )
    assert await coordinator._async_update_data() is response

    assert dtu.is_encrypted is True
    assert entry.data[CONF_IS_ENCRYPTED] is True


async def test_app_info_turns_encryption_off_when_dfs_is_zero(
    hass: HomeAssistant,
) -> None:
    """A DTU reporting dfs == 0 announces no flags, encryption included.

    Regression test for the guard that skipped the sync on a falsy dfs, which
    made turning encryption back off unreachable through this code path.
    """
    dtu = FakeDTU(is_encrypted=True, enc_rand=RAND)
    dtu.app_info_response = type("R", (), {"dtu_info": make_dtu_info(0)})()

    coordinator, entry = await make_app_info_coordinator(
        hass, dtu, {CONF_IS_ENCRYPTED: True, CONF_ENC_RAND: RAND.hex()}
    )
    await coordinator._async_update_data()

    assert dtu.is_encrypted is False
    assert dtu.enc_rand == b""
    assert entry.data[CONF_IS_ENCRYPTED] is False
    assert entry.data[CONF_ENC_RAND] == ""


async def test_app_info_unavailable(hass: HomeAssistant) -> None:
    """An offline DTU must not touch the stored encryption state."""
    dtu = FakeDTU(is_encrypted=True, enc_rand=RAND)
    dtu.app_info_response = None

    coordinator, entry = await make_app_info_coordinator(
        hass, dtu, {CONF_IS_ENCRYPTED: True, CONF_ENC_RAND: RAND.hex()}
    )
    assert await coordinator._async_update_data() is None

    assert dtu.is_encrypted is True
    assert entry.data[CONF_ENC_RAND] == RAND.hex()
