import logging
import ipaddress
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    DOMAIN,
    CONF_UPDATE_INTERVAL,
    DEFAULT_UPDATE_INTERVAL,
    MIN_UPDATE_INTERVAL
)

_LOGGER = logging.getLogger(__name__)

DATA_SCHEMA = vol.Schema({
        vol.Required(CONF_HOST): str,
        vol.Optional(
            CONF_UPDATE_INTERVAL,
            default=DEFAULT_UPDATE_INTERVAL.seconds,
        ): vol.All(vol.Coerce(int), vol.Range(min=MIN_UPDATE_INTERVAL.seconds)),
})

class HoymilesInverterFlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """Hoymiles Inverter config flow."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_POLL

    async def async_step_user(self, user_input=None):
        """Handle a flow initiated by the user."""
        errors = {}

        if user_input is not None:
            host = user_input[CONF_HOST]
            update_interval = user_input[CONF_UPDATE_INTERVAL]

            # Validate the provided host and update_interval
            if not is_valid_host(host):
                errors[CONF_HOST] = "invalid_host"

            if not validate_update_interval(update_interval):
                errors[CONF_UPDATE_INTERVAL] = "invalid_update_interval"

            if not errors:
                return self.async_create_entry(
                    title=host, data={CONF_HOST: host, CONF_UPDATE_INTERVAL: update_interval}
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
        except (socket.herror, ValueError):
            return False

async def validate_update_interval(update_interval):
    """Validate the provided update_interval."""
    # Add your validation logic here
    # Return True if the update_interval is valid, False otherwise
    return True
