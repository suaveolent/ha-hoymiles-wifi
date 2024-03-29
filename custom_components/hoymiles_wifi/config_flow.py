"""Config flow for Hoymiles."""
from datetime import timedelta
import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from hoymiles_wifi.dtu import DTU
from hoymiles_wifi.protobuf import APPInfomationData_pb2

from .const import (
    CONF_DTU_SERIAL_NUMBER,
    CONF_INVERTERS,
    CONF_PORTS,
    CONF_UPDATE_INTERVAL,
    CONFIG_VERSION,
    DEFAULT_UPDATE_INTERVAL_SECONDS,
    DOMAIN,
    MIN_UPDATE_INTERVAL_SECONDS,
)
from .error import CannotConnect
from .util import async_get_config_entry_data_for_host

_LOGGER = logging.getLogger(__name__)

DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Optional(
            CONF_UPDATE_INTERVAL,
            default=timedelta(seconds=DEFAULT_UPDATE_INTERVAL_SECONDS).seconds,
        ): vol.All(
            vol.Coerce(int),
            vol.Range(min=timedelta(seconds=MIN_UPDATE_INTERVAL_SECONDS).seconds),
        ),
    }
)


class HoymilesInverterConfigFlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """Hoymiles Inverter config flow."""

    VERSION = CONFIG_VERSION

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle a flow initiated by the user."""
        errors = {}

        if user_input is not None:
            self._async_abort_entries_match(user_input)
            host = user_input[CONF_HOST]
            update_interval = user_input.get(
                CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL_SECONDS
            )

            try:
                dtu_sn, inverters, ports = await async_get_config_entry_data_for_host(
                    host
                )
            except CannotConnect:
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(
                    title=host,
                    data={
                        CONF_HOST: host,
                        CONF_UPDATE_INTERVAL: update_interval,
                        CONF_DTU_SERIAL_NUMBER: dtu_sn,
                        CONF_INVERTERS: inverters,
                        CONF_PORTS: ports,
                    },
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


async def get_real_data_new(
    hass: HomeAssistant, host: str
) -> APPInfomationData_pb2.APPInfoDataResDTO:
    """Test if the host is reachable and is actually a Hoymiles device."""

    dtu = DTU(host)
    response = await dtu.get_real_data_new()
    if response is None:
        raise CannotConnect
    return response
