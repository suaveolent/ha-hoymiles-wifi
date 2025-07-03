"""Utils for hoymiles-wifi."""

from typing import Union
import logging

from hoymiles_wifi.dtu import DTU
from hoymiles_wifi.hoymiles import generate_inverter_serial_number

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
]:
    """Get data for config entry from host."""

    single_phase_inverters = []
    three_phase_inverters = []
    ports = []
    meters = []
    hybrid_inverters = []
    dtu_sn = None

    dtu = DTU(host)

    real_data = await dtu.async_get_real_data_new()

    if real_data is not None:
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
        gateway_info = await dtu.async_get_gateway_info()

        if gateway_info is not None:
            registry = await dtu.async_get_energy_storage_registry(
                dtu_serial_number=gateway_info.serial_number
            )

            if registry is not None:
                dtu_sn = str(gateway_info.serial_number)

                hybrid_inverters = [
                    {
                        "inverter_serial_number": inverter.serial_number,
                        "model_name": inverter.model_name,
                    }
                    for inverter in registry.inverters
                ]
            else:
                logging.error(
                    "Energy storage registry is None. Cannot connect to DTU or invalid response received!"
                )
                raise CannotConnect
        else:
            logging.error(
                "RealData new and Gatewayinfo and is None. Cannot connect to DTU or invalid response received!"
            )
        raise CannotConnect

    return (
        dtu_sn,
        single_phase_inverters,
        three_phase_inverters,
        ports,
        meters,
        hybrid_inverters,
    )
