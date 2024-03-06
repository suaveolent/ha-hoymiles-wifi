"""Config flow for Hoymiles."""
from datetime import timedelta
import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError
from hoymiles_wifi.inverter import Inverter
from hoymiles_wifi.protobuf import APPInfomationData_pb2
from hoymiles_wifi.utils import generate_inverter_serial_number

from .const import (
    CONF_DTU_SERIAL_NUMBER,
    CONF_INVERTERS,
    CONF_PORTS,
    CONF_SENSOR_PREFIX,
    CONF_UPDATE_INTERVAL,
    DEFAULT_UPDATE_INTERVAL_SECONDS,
    DOMAIN,
    MIN_UPDATE_INTERVAL_SECONDS,
)

_LOGGER = logging.getLogger(__name__)

DATA_SCHEMA = vol.Schema({
        vol.Required(CONF_HOST): str,
        vol.Optional(
            CONF_UPDATE_INTERVAL,
            default=timedelta(seconds=DEFAULT_UPDATE_INTERVAL_SECONDS).seconds,
        ): vol.All(vol.Coerce(int), vol.Range(min=timedelta(seconds=MIN_UPDATE_INTERVAL_SECONDS).seconds)),
        vol.Optional(CONF_SENSOR_PREFIX): str,
})

class HoymilesInverterConfigFlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """Hoymiles Inverter config flow."""

    VERSION = 2

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle a flow initiated by the user."""
        errors = {}

        if user_input is not None:
            self._async_abort_entries_match(user_input)
            host = user_input[CONF_HOST]
            update_interval = user_input.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL_SECONDS)
            sensor_prefix = user_input.get(CONF_SENSOR_PREFIX, "")

            try:
                real_data = await get_real_data_new.async_get_real_data_new()
            except CannotConnect:
                errors["base"] = "cannot_connect"
            else:

                dtu_sn = real_data.device_serial_number
                inverters = []

                for sgs_data in real_data.sgs_data:
                    inverter_serial = generate_inverter_serial_number(sgs_data.serial_number)
                    inverters.append(inverter_serial)

                ports = []
                for pv_data in real_data.pv_data:
                    inverter_serial = generate_inverter_serial_number(pv_data.serial_number)
                    port_number = pv_data.port_number
                    ports.append({
                        "inverter_serial_number": inverter_serial,
                        "port_number": port_number
                    })

                return self.async_create_entry(
                    title=host, data= {
                        CONF_HOST: host,
                        CONF_SENSOR_PREFIX: sensor_prefix,
                        CONF_UPDATE_INTERVAL: update_interval,
                        CONF_DTU_SERIAL_NUMBER: dtu_sn,
                        CONF_INVERTERS: inverters,
                        CONF_PORTS: ports,
                    }
                )

        return self.async_show_form(
            step_id="user", data_schema=DATA_SCHEMA, errors=errors
        )

    async def async_step_import(self, import_config):
        """Import a configuration."""
        # Validate the imported configuration, and create an entry if valid
        return self.async_create_entry(
            title=import_config[CONF_HOST], data=import_config
        )


async def get_real_data_new(hass: HomeAssistant, host: str) -> APPInfomationData_pb2.APPInfoDataResDTO:
    """Test if the host is reachable and is actually a Hoymiles HMS device."""

    inverter = Inverter(host)
    response = await inverter.get_real_data_new()
    if(response is None):
        raise CannotConnect
    return response


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""
