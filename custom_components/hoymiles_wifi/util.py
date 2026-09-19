"""Utils for hoymiles-wifi."""

from typing import TYPE_CHECKING, Union
import asyncio
import logging

from hoymiles_wifi.dtu import DTU
from hoymiles_wifi.hoymiles import generate_inverter_serial_number
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback

from hoymiles_wifi.const import IS_ENCRYPTED_BIT_INDEX

from .error import CannotConnect

from .const import (
    CONF_ENC_RAND,
    CONF_IS_ENCRYPTED,
    DEFAULT_TIMEOUT_SECONDS,
    ENC_RAND_LENGTH,
)

if TYPE_CHECKING:
    from hoymiles_wifi.protobuf.APPInfomationData_pb2 import APPDtuInfoMO

_LOGGER = logging.getLogger(__name__)


async def async_get_config_entry_data_for_host(
    host,
) -> tuple[
    str,
    list[str],
    list[dict[str, Union[str, int]]],
    list[dict[str, Union[str, int]]],
    list[dict[str, Union[str, int]]],
    bool,
    str,
]:
    """Get data for config entry from host."""

    single_phase_inverters = []
    three_phase_inverters = []
    ports = []
    meters = []
    hybrid_inverters = []
    dtu_sn = None
    is_encrypted = False
    enc_rand = ""

    dtu = DTU(host, timeout=DEFAULT_TIMEOUT_SECONDS)

    app_information_data = await dtu.async_app_information_data()

    if app_information_data and app_information_data.dtu_info.dfs:
        if is_encrypted_dtu(app_information_data.dtu_info.dfs):
            logging.debug("DTU is encrypted.")
            is_encrypted = True
            enc_rand = app_information_data.dtu_info.enc_rand.hex()
            dtu = DTU(
                host,
                is_encrypted=is_encrypted,
                enc_rand=bytes.fromhex(enc_rand),
                timeout=DEFAULT_TIMEOUT_SECONDS,
            )
            await asyncio.sleep(2)

    logging.debug("Trying get_real_data_new()!")
    real_data = await dtu.async_get_real_data_new()
    logging.debug(f"RealDataNew call done. Result: {real_data}")

    if real_data:
        dtu_sn = real_data.device_serial_number

        single_phase_inverters = [
            generate_inverter_serial_number(sgs_data.serial_number)
            for sgs_data in real_data.sgs_data
        ]

        three_phase_inverters = [
            generate_inverter_serial_number(tgs_data.serial_number)
            for tgs_data in real_data.tgs_data
        ]

        ports = [
            {
                "inverter_serial_number": generate_inverter_serial_number(
                    pv_data.serial_number
                ),
                "port_number": pv_data.port_number,
            }
            for pv_data in real_data.pv_data
        ]

        meters = [
            {
                "meter_serial_number": generate_inverter_serial_number(
                    meter_data.serial_number
                ),
                "device_type": meter_data.device_type,
            }
            for meter_data in real_data.meter_data
        ]
    else:
        logging.debug(
            "RealDataNew is None. Sleeping for 5s before trying get_gateway_info()!"
        )
        await asyncio.sleep(5)
        gateway_info = await dtu.async_get_gateway_info()
        logging.debug(f"GatewayInfo call done. Result: {gateway_info}")

        if gateway_info:
            logging.debug("Trying get energy storage registry call.")
            registry = await dtu.async_get_energy_storage_registry(
                dtu_serial_number=gateway_info.serial_number
            )
            logging.debug(f"Get energy storage registry call done. Result: {registry}")

            if registry:
                dtu_sn = str(gateway_info.serial_number)

                hybrid_inverters = [
                    {
                        "inverter_serial_number": inverter.serial_number,
                        "model_name": inverter.model_name,
                    }
                    for inverter in registry.inverters
                ]
                logging.debug(f"Hybrid inverters: {hybrid_inverters}")
            else:
                logging.error(
                    "Energy storage registry is None. Cannot connect to DTU or invalid response received!"
                )
                raise CannotConnect
        else:
            logging.error(
                "RealDataNew and GatewayInfo is None. Cannot connect to DTU or invalid response received!"
            )
            raise CannotConnect

    return (
        dtu_sn,
        single_phase_inverters,
        three_phase_inverters,
        ports,
        meters,
        hybrid_inverters,
        is_encrypted,
        enc_rand,
    )


def is_encrypted_dtu(dfs: int) -> bool:
    """Check if the DTU is encrypted."""
    return (dfs >> IS_ENCRYPTED_BIT_INDEX) & 1


@callback
def async_sync_encryption_state(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    dtu: DTU,
    dtu_info: "APPDtuInfoMO",
) -> None:
    """Align the stored and live encryption state with what the DTU reports.

    The DTU announces whether it expects encrypted payloads via a bit in its
    ``dfs`` field. A firmware update can flip that bit, so both the live DTU
    object and the config entry have to follow, otherwise every non-app-info
    request (app info is never encrypted) silently fails to parse.
    """
    encryption_announced = bool(is_encrypted_dtu(dtu_info.dfs))

    # The announcement is only usable together with a key of the exact length
    # the cipher expects. `derive_aes_128_key` asserts on it, and that assert
    # fires from `generate_message`, outside the library's own error handling,
    # so an unusable key would raise on every single request rather than
    # degrade. Treating it as unencrypted keeps requests flowing in plaintext,
    # which is the only thing that can still work here.
    if encryption_announced and len(dtu_info.enc_rand) != ENC_RAND_LENGTH:
        _LOGGER.warning(
            "DTU announced encryption but reported an unusable encryption random "
            "of %d bytes (expected %d). Continuing unencrypted",
            len(dtu_info.enc_rand),
            ENC_RAND_LENGTH,
        )
        is_encrypted = False
    else:
        is_encrypted = encryption_announced

    enc_rand = dtu_info.enc_rand.hex() if is_encrypted else ""

    stored_is_encrypted = config_entry.data.get(CONF_IS_ENCRYPTED, False)
    stored_enc_rand = config_entry.data.get(CONF_ENC_RAND, "") or ""

    # Always keep the live DTU in sync, it is rebuilt from the config entry on
    # every setup but may be long-lived in between.
    dtu.is_encrypted = is_encrypted
    dtu.enc_rand = bytes.fromhex(enc_rand) if enc_rand else b""

    if stored_is_encrypted == is_encrypted and stored_enc_rand == enc_rand:
        return

    _LOGGER.debug(
        "Updating encryption state in config entry: is_encrypted %s -> %s, "
        "enc_rand %s -> %s",
        stored_is_encrypted,
        is_encrypted,
        stored_enc_rand,
        enc_rand,
    )

    new_data = {
        **config_entry.data,
        CONF_IS_ENCRYPTED: is_encrypted,
        CONF_ENC_RAND: enc_rand,
    }
    hass.config_entries.async_update_entry(config_entry, data=new_data)
