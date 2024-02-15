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

from .const import (
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
                await test_host_connection(self.hass, host)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(
                    title=host, data={
                        CONF_HOST: host,
                        CONF_SENSOR_PREFIX: sensor_prefix,
                        CONF_UPDATE_INTERVAL: update_interval
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


async def test_host_connection(hass: HomeAssistant, host: str):
    """Test if the host is reachable and is actually a Hoymiles HMS device."""

    inverter = Inverter(host)
    response = await inverter.async_heartbeat()
    if(response is None):
        raise CannotConnect

class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""
