from homeassistant.core import HomeAssistant, ServiceCall
from hoymiles_wifi.dtu import DTU

from hoymiles_wifi.hoymiles import BMSWorkingMode

from custom_components.hoymiles_wifi.const import HASS_DTU, DOMAIN
from homeassistant.helpers.device_registry import async_get as async_get_dev_reg

from hoymiles_wifi.utils import parse_time_periods_input, parse_time_settings_input


async def async_handle_set_bms_mode(call: ServiceCall):
    device_ids = call.target.device_id
    hass = call.hass
    if not device_ids:
        raise ValueError("No target devices selected.")

    device_registry = async_get_dev_reg(hass)

    serial = None

    # Access device_id from the service call's target
    for device_id in call.data.get("device_id", []):
        device = device_registry.async_get(device_id)
        if device:
            hass.logger.info(f"Device: {device.name} ({device.id})")

    if not serial:
        raise ValueError(f"No serial number found for device {device_id}")

    mode_str = call.data["bms_mode"]
    bms_working_mode = BMSWorkingMode[mode_str.upper()]
    rev_soc = call.data.get("rev_soc")
    max_power = call.data.get("max_power")
    peak_soc = call.data.get("peak_soc")
    peak_meter_power = call.data.get("peak_meter_power")
    time_settings_str = call.data.get("time_settings")
    time_periods_str = call.data.get("time_periods")

    time_settings = None
    time_periods = None

    if rev_soc is None:
        raise ValueError("No reserve SOC provided!")

    if bms_working_mode == BMSWorkingMode.ECONOMIC:
        time_settings = parse_time_settings_input(time_settings_str)
        if not time_settings:
            raise ValueError("Invalid time settings!")

    elif bms_working_mode in (
        BMSWorkingMode.FORCED_CHARGING,
        BMSWorkingMode.FORCED_DISCHARGE,
    ):
        if max_power is None:
            raise ValueError("No max power provided!")

    elif bms_working_mode == BMSWorkingMode.PEAK_SHAVING:
        if peak_soc is None:
            raise ValueError("No peak SOC provided!")
        if peak_meter_power is None:
            raise ValueError("No peak meter power provided!")

    elif bms_working_mode == BMSWorkingMode.TIME_OF_USE:
        time_periods = parse_time_periods_input(time_periods_str)
        if not time_periods:
            raise ValueError("Invalid time periods!")

    # === Call the actual API ===

    await dtu.async_set_energy_storage_working_mode(
        dtu_serial_number=dtu_serial_number,
        inverter_serial_number=serial,
        bms_working_mode=bms_working_mode,
        rev_soc=rev_soc,
        time_settings=time_settings,
        max_power=max_power,
        peak_soc=peak_soc,
        peak_meter_power=peak_meter_power,
        time_periods=time_periods,
    )
