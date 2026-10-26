"""Utils for hoymiles-wifi."""

import asyncio
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from hoymiles_wifi.const import IS_ENCRYPTED_BIT_INDEX
from hoymiles_wifi.dtu import DTU
from hoymiles_wifi.hoymiles import generate_inverter_serial_number

from .const import CONF_ENC_RAND, CONF_IS_ENCRYPTED, DEFAULT_TIMEOUT_SECONDS
from .error import CannotConnect

_LOGGER = logging.getLogger(__name__)


async def async_get_config_entry_data_for_host(
    host,
) -> tuple[
    str,
    list[str],
    list[dict[str, str | int]],
    list[dict[str, str | int]],
    list[dict[str, str | int]],
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

    if (
        app_information_data
        and app_information_data.dtu_info.dfs
        and is_encrypted_dtu(app_information_data.dtu_info.dfs)
    ):
        _LOGGER.debug("DTU is encrypted.")
        is_encrypted = True
        enc_rand = app_information_data.dtu_info.enc_rand.hex()
        dtu = DTU(
            host,
            is_encrypted=is_encrypted,
            enc_rand=bytes.fromhex(enc_rand),
            timeout=DEFAULT_TIMEOUT_SECONDS,
        )
        await asyncio.sleep(2)

    _LOGGER.debug("Trying get_real_data_new()!")
    real_data = await dtu.async_get_real_data_new()
    _LOGGER.debug("RealDataNew call done. Result: %s", real_data)

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
        _LOGGER.debug(
            "RealDataNew is None. Sleeping for 5s before trying get_gateway_info()!"
        )
        await asyncio.sleep(5)
        gateway_info = await dtu.async_get_gateway_info()
        _LOGGER.debug("GatewayInfo call done. Result: %s", gateway_info)

        if gateway_info:
            _LOGGER.debug("Trying get energy storage registry call.")
            registry = await dtu.async_get_energy_storage_registry(
                dtu_serial_number=gateway_info.serial_number
            )
            _LOGGER.debug("Get energy storage registry call done. Result: %s", registry)

            if registry:
                dtu_sn = str(gateway_info.serial_number)

                hybrid_inverters = [
                    {
                        "inverter_serial_number": inverter.serial_number,
                        "model_name": inverter.model_name,
                    }
                    for inverter in registry.inverters
                ]
                _LOGGER.debug("Hybrid inverters: %s", hybrid_inverters)
            else:
                _LOGGER.error(
                    "Energy storage registry is None. Cannot connect to DTU or invalid response received!"
                )
                raise CannotConnect
        else:
            _LOGGER.error(
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


async def async_check_and_update_enc_rand(
    hass: HomeAssistant, config_entry: ConfigEntry, dtu: DTU, enc_rand: str
) -> None:
    """Apply and persist encryption detected through app info."""
    dtu.enc_rand = bytes.fromhex(enc_rand)
    if not dtu.is_encrypted:
        _LOGGER.info("DTU reports encryption enabled; enabling encrypted communication")
    dtu.is_encrypted = True

    if (
        not config_entry.data.get(CONF_IS_ENCRYPTED, False)
        or config_entry.data.get(CONF_ENC_RAND) != enc_rand
    ):
        new_data = {
            **config_entry.data,
            CONF_IS_ENCRYPTED: True,
            CONF_ENC_RAND: enc_rand,
        }
        hass.config_entries.async_update_entry(config_entry, data=new_data)
