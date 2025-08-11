from homeassistant.core import HomeAssistant, ServiceCall
from hoymiles_wifi.dtu import DTU

from hoymiles_wifi.hoymiles import BMSWorkingMode

from custom_components.hoymiles_wifi.const import HASS_DTU, DOMAIN
from homeassistant.helpers.device_registry import async_get as async_get_dev_reg
from homeassistant.helpers.entity_registry import async_get as async_get_ent_reg


async def async_set_bms_mode(hass: HomeAssistant, call: ServiceCall):
    dtu: DTU = hass.data[DOMAIN][HASS_DTU]

    device_ids = call.target.device_id
    if not device_ids:
        raise ValueError("No target devices selected.")

    dev_reg = async_get_dev_reg(hass)
    ent_reg = async_get_ent_reg(hass)

    for device_id in device_ids:
        related_entities = [
            ent
            for ent in ent_reg.entities.values()
            if ent.device_id == device_id and ent.domain == "sensor"
        ]

    serial = None

    for ent in related_entities:
        state = hass.states.get(ent.entity_id)
        if state and "inverter_serial_number" in state.attributes:
            serial = state.attributes["inverter_serial_number"]
            break

    if not serial:
        raise ValueError(f"No serial number found for device {device_id}")

    mode_str = call.data["mode"]
    mode = BMSWorkingMode[mode_str.upper()]  # converts to Enum
    rev_soc = call.data["rev_soc"]
    max_power = call.data.get("max_power")
    peak_soc = call.data.get("peak_soc")
    peak_meter_power = call.data.get("peak_meter_power")
    time_settings = call.data.get("time_settings")
    time_periods = call.data.get("time_periods")

    # Construct kwargs based on mode
    kwargs = {
        "bms_working_mode": mode,
        "inverter_serial_number": serial,
        "rev_soc": rev_soc,
    }

    # Add conditional params
    if mode in [5, 6] and max_power is not None:
        kwargs["max_power"] = max_power
    elif mode == 7:
        kwargs["peak_soc"] = peak_soc
        kwargs["peak_meter_power"] = peak_meter_power
    elif mode == 2 and time_settings:
        kwargs["time_settings"] = time_settings
    elif mode == 8 and time_periods:
        kwargs["time_periods"] = time_periods

    # Call the library function
    await dtu.async_set_energy_storage_working_mode(**kwargs)
