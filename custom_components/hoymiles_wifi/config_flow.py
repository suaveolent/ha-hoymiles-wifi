"""Config flow for Hoymiles."""

from datetime import timedelta
import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from hoymiles_wifi.dtu import DTU
from hoymiles_wifi.protobuf import APPInfomationData_pb2

from .const import (
    CONF_DTU_SERIAL_NUMBER,
    CONF_INVERTERS,
    CONF_THREE_PHASE_INVERTERS,
    CONF_PORTS,
    CONF_METERS,
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
            host = user_input[CONF_HOST]
            update_interval = user_input.get(
                CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL_SECONDS
            )

            try:
                (
                    dtu_sn,
                    single_phase_inverters,
                    three_phase_inverters,
                    ports,
                    meters,
                ) = await async_get_config_entry_data_for_host(host)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(dtu_sn)
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=host,
                    data={
                        CONF_HOST: host,
                        CONF_UPDATE_INTERVAL: update_interval,
                        CONF_DTU_SERIAL_NUMBER: dtu_sn,
                        CONF_INVERTERS: single_phase_inverters,
                        CONF_THREE_PHASE_INVERTERS: three_phase_inverters,
                        CONF_PORTS: ports,
                        CONF_METERS: meters,
                    },
                )

        return self.async_show_form(
            step_id="user", data_schema=DATA_SCHEMA, errors=errors
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle a reconfiguration flow initialized by the user."""

        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        assert entry is not None

        errors = {}

        if user_input is not None:
            host = user_input[CONF_HOST]
            update_interval = user_input.get(
                CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL_SECONDS
            )

            try:
                (
                    dtu_sn,
                    single_phase_inverters,
                    three_phase_inverters,
                    ports,
                    meters,
                ) = await async_get_config_entry_data_for_host(host)
            except CannotConnect:
                errors["base"] = "cannot_connect"

            else:
                if dtu_sn != entry.unique_id:
                    return self.async_abort(reason="another_device")

                data = {
                    CONF_HOST: host,
                    CONF_UPDATE_INTERVAL: update_interval,
                    CONF_DTU_SERIAL_NUMBER: dtu_sn,
                    CONF_INVERTERS: single_phase_inverters,
                    CONF_THREE_PHASE_INVERTERS: three_phase_inverters,
                    CONF_PORTS: ports,
                    CONF_METERS: meters,
                }

                self.hass.config_entries.async_update_entry(
                    entry, data=data, version=CONFIG_VERSION
                )
                result = await self.hass.config_entries.async_reload(entry.entry_id)
                if not result:
                    errors["base"] = "unknown"
                else:
                    return self.async_abort(reason="reconfigure_successful")

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST, default=entry.data[CONF_HOST]): str,
                    vol.Optional(
                        CONF_UPDATE_INTERVAL,
                        default=entry.data[CONF_UPDATE_INTERVAL],
                    ): vol.All(
                        vol.Coerce(int),
                        vol.Range(
                            min=timedelta(seconds=MIN_UPDATE_INTERVAL_SECONDS).seconds
                        ),
                    ),
                }
            ),
            errors=errors,
        )
