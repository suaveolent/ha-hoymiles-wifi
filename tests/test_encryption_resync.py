"""Tests for on-demand resynchronization of the DTU encryption key."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from hoymiles_wifi.dtu import NetworkState
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hoymiles_wifi.const import (
    CONF_CLOUD_PAUSE,
    CONF_ENC_RAND,
    CONF_IS_ENCRYPTED,
    DOMAIN,
    ENC_RAND_RESYNC_MIN_INTERVAL_SECONDS,
)
from custom_components.hoymiles_wifi.coordinator import (
    HoymilesAppInfoUpdateCoordinator,
    HoymilesRealDataUpdateCoordinator,
)

OLD_KEY = "00112233"
NEW_KEY = "44556677"


def _encrypted_dtu(state: NetworkState) -> MagicMock:
    dtu = MagicMock()
    dtu.is_encrypted = True
    dtu.enc_rand = bytes.fromhex(OLD_KEY)
    dtu.get_state.return_value = state
    return dtu


def _app_info_response(enc_rand: str) -> SimpleNamespace:
    return SimpleNamespace(
        dtu_info=SimpleNamespace(dfs=1 << 30, enc_rand=bytes.fromhex(enc_rand))
    )


def _setup(hass, dtu):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"host": "192.168.1.228", CONF_IS_ENCRYPTED: True, CONF_ENC_RAND: OLD_KEY},
    )
    entry.add_to_hass(hass)
    data = HoymilesRealDataUpdateCoordinator(hass, dtu, entry, timedelta(seconds=35))
    app_info = HoymilesAppInfoUpdateCoordinator(hass, dtu, entry, timedelta(hours=2))
    data.set_encryption_resync(app_info.async_resync_encryption)
    return entry, data, app_info


async def test_new_key_is_fetched_and_data_retried(hass):
    """A DTU that answers undecodable data triggers an immediate key refresh."""
    dtu = _encrypted_dtu(NetworkState.Unknown)
    entry, data, _ = _setup(hass, dtu)
    live = SimpleNamespace(sgs_data=[])
    dtu.async_get_real_data_new = AsyncMock(side_effect=[None, live])
    dtu.async_app_information_data = AsyncMock(return_value=_app_info_response(NEW_KEY))

    with patch(
        "custom_components.hoymiles_wifi.coordinator.is_encrypted_dtu",
        return_value=True,
    ):
        await data.async_refresh()

    assert data.last_update_success
    assert data.data is live
    assert dtu.enc_rand == bytes.fromhex(NEW_KEY)
    assert entry.data[CONF_ENC_RAND] == NEW_KEY
    assert dtu.async_get_real_data_new.await_count == 2


async def test_offline_dtu_does_not_trigger_resync(hass):
    """An unreachable DTU (e.g. at night) does not cause extra requests."""
    dtu = _encrypted_dtu(NetworkState.Offline)
    _, data, _ = _setup(hass, dtu)
    dtu.async_get_real_data_new = AsyncMock(return_value=None)
    dtu.async_app_information_data = AsyncMock()

    await data.async_refresh()

    assert not data.last_update_success
    dtu.async_app_information_data.assert_not_awaited()
    dtu.async_get_real_data_new.assert_awaited_once()


async def test_unencrypted_dtu_does_not_trigger_resync(hass):
    """Unencrypted DTUs keep the existing behaviour."""
    dtu = _encrypted_dtu(NetworkState.Unknown)
    dtu.is_encrypted = False
    _, data, _ = _setup(hass, dtu)
    dtu.async_get_real_data_new = AsyncMock(return_value=None)
    dtu.async_app_information_data = AsyncMock()

    await data.async_refresh()

    dtu.async_app_information_data.assert_not_awaited()


async def test_resync_is_rate_limited_and_skips_retry_when_key_unchanged(hass):
    """Repeated failures query app info at most once per interval."""
    dtu = _encrypted_dtu(NetworkState.Unknown)
    _, data, _ = _setup(hass, dtu)
    dtu.async_get_real_data_new = AsyncMock(return_value=None)
    dtu.async_app_information_data = AsyncMock(return_value=_app_info_response(OLD_KEY))

    with (
        patch(
            "custom_components.hoymiles_wifi.coordinator.is_encrypted_dtu",
            return_value=True,
        ),
        patch(
            "custom_components.hoymiles_wifi.coordinator.monotonic", return_value=1000
        ) as clock,
    ):
        await data.async_refresh()
        assert dtu.async_app_information_data.await_count == 1
        # Key unchanged: no second data request.
        assert dtu.async_get_real_data_new.await_count == 1

        clock.return_value = 1000 + ENC_RAND_RESYNC_MIN_INTERVAL_SECONDS - 1
        await data.async_refresh()
        assert dtu.async_app_information_data.await_count == 1

        clock.return_value = 1000 + ENC_RAND_RESYNC_MIN_INTERVAL_SECONDS
        await data.async_refresh()
        assert dtu.async_app_information_data.await_count == 2


async def test_resync_crossing_cloud_pause_defers_retry(hass):
    """Keep cached data if key recovery finishes inside the cloud's quiet window."""
    dtu = _encrypted_dtu(NetworkState.Unknown)
    entry, data, app_info = _setup(hass, dtu)
    hass.config_entries.async_update_entry(
        entry, data={**entry.data, CONF_CLOUD_PAUSE: 30}
    )
    live = SimpleNamespace(sgs_data=[])
    dtu.async_get_real_data_new = AsyncMock(return_value=live)

    with (
        patch(
            "custom_components.hoymiles_wifi.coordinator.dt_util.utcnow",
            return_value=datetime(2026, 10, 27, 12, 4, 48, tzinfo=UTC),
        ) as now,
        patch(
            "custom_components.hoymiles_wifi.coordinator.is_encrypted_dtu",
            return_value=True,
        ),
    ):
        await data.async_refresh()
        last_success = data._last_successful_fetch
        dtu.async_get_real_data_new = AsyncMock(return_value=None)
        now.return_value = datetime(2026, 10, 27, 12, 4, 49, tzinfo=UTC)

        async def resync_response():
            now.return_value = datetime(2026, 10, 27, 12, 4, 50, tzinfo=UTC)
            return _app_info_response(NEW_KEY)

        dtu.async_app_information_data = AsyncMock(side_effect=resync_response)
        await data.async_refresh()

        assert dtu.enc_rand == bytes.fromhex(NEW_KEY)
        assert entry.data[CONF_ENC_RAND] == NEW_KEY
        dtu.async_app_information_data.assert_awaited_once()
        dtu.async_get_real_data_new.assert_awaited_once()
        assert data.data is live
        assert data.last_update_success
        assert data.data_is_stale
        assert data._last_successful_fetch == last_success

        now.return_value = datetime(2026, 10, 27, 12, 5, 20, tzinfo=UTC)
        dtu.async_get_real_data_new.return_value = live
        await data.async_refresh()
        assert dtu.async_get_real_data_new.await_count == 2
        assert not data.data_is_stale
        assert data.last_update_success

    await data.async_shutdown()
    await app_info.async_shutdown()
