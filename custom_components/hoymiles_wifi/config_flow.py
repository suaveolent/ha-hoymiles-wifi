import logging
import ipaddress
import voluptuous as vol
from datetime import timedelta
import socket

from homeassistant import config_entries
from homeassistant.const import CONF_HOST
from homeassistant.core import callback

from .const import (
    DOMAIN,
    CONF_UPDATE_INTERVAL,
    CONF_SENSOR_PREFIX,
    DEFAULT_UPDATE_INTERVAL_SECONDS,
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

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_POLL

    async def async_step_user(self, user_input=None):
        """Handle a flow initiated by the user."""
        errors = {}

        if user_input is not None:
            host = user_input[CONF_HOST]
            update_interval = user_input.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL_SECONDS)
            sensor_prefix = user_input.get(CONF_SENSOR_PREFIX, "")

            errors = await validate_configuration(host, update_interval, sensor_prefix)

            if not errors:
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

            _LOGGER.error(f"Host {host}, update_interval: {update_interval}, sensor_prefix: {sensor_prefix}")

            errors = await validate_configuration(host, update_interval, sensor_prefix)

            if not errors:
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
            
async def validate_configuration(host, update_interval, sensor_prefix):
    """Validate the provided configuration."""
    errors = {}

    if not is_valid_host(host):
        errors[CONF_HOST] = "invalid_host"

    if not await validate_update_interval(update_interval):
        errors[CONF_UPDATE_INTERVAL] = "invalid_update_interval"

    return errors
    

def is_valid_host(host):
    """Check if the provided value is a valid DNS name or IP address."""
    try:
        # Try to parse the host as an IP address
        ipaddress.ip_address(host)
        return True
    except ValueError:
        # If parsing as an IP address fails, try as a DNS name
        try:
            ipaddress.ip_address(socket.gethostbyname(host))
            return True
        except (socket.herror, ValueError, socket.gaierror):
            return False
        

async def validate_update_interval(update_interval):
    """Validate the provided update_interval."""
    # Return True if the update_interval is valid, False otherwise
    return True

