"""Utils for hoymiles-wifi."""

from typing import Union
import asyncio
import logging

from hoymiles_wifi.dtu import DTU
from hoymiles_wifi.hoymiles import generate_inverter_serial_number

from hoymiles_wifi.const import IS_ENCRYPTED_BIT_INDEX

from .error import CannotConnect

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

    dtu = DTU(host)

    app_information_data = await dtu.async_app_information_data()

    if app_information_data and app_information_data.dtu_info.dfs:
        if (app_information_data.dtu_info.dfs >> IS_ENCRYPTED_BIT_INDEX) & 1:
            logging.debug("DTU is encrypted.")
            is_encrypted = True
            enc_rand = app_information_data.dtu_info.enc_rand.hex()
            dtu = DTU(host, is_encrypted=is_encrypted, enc_rand=enc_rand)
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
