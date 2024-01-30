"""Config flow for Hoymiles."""
from datetime import timedelta
import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult

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


    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Get the options flow for this handler."""
        return HoymilesInverterOptionsFlowHandler(config_entry)



class HoymilesInverterOptionsFlowHandler(config_entries.OptionsFlow):
    """Hoymiles Inverter options flow."""

    def __init__(self, config_entry):
        """Initialize the options flow for Hoymiles Inverter."""
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        """Manage the options."""
        return await self.async_step_user_options()

    async def async_step_user_options(self, user_input=None):
        """Handle a flow initiated by the user."""

        errors = {}

        if user_input is not None:
            host = user_input.get(CONF_HOST)
            update_interval = user_input.get(CONF_UPDATE_INTERVAL)
            sensor_prefix = user_input.get(CONF_SENSOR_PREFIX)

            return self.async_create_entry(
                    title="", data={
                        CONF_HOST: host,
                        CONF_SENSOR_PREFIX: sensor_prefix,
                        CONF_UPDATE_INTERVAL: update_interval
                    }
                )

        options = self.config_entry.options
        host = options.get(CONF_HOST)
        update_interval = options.get(CONF_UPDATE_INTERVAL)
        sensor_prefix = options.get(CONF_SENSOR_PREFIX)

        return self.async_show_form(
            step_id="user_options",
            data_schema=vol.Schema({
                vol.Required(CONF_HOST, default=host): str,
                vol.Optional(
                    CONF_UPDATE_INTERVAL,
                    default=update_interval
                ): vol.All(vol.Coerce(int), vol.Range(min=timedelta(seconds=MIN_UPDATE_INTERVAL_SECONDS).seconds)),
                vol.Optional(CONF_SENSOR_PREFIX, description={"suggested_value": sensor_prefix}): str,
            }),
            errors=errors,
        )
