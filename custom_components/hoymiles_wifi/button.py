"""Support for Hoymiles buttons."""

import dataclasses
from inspect import signature
from dataclasses import dataclass

from homeassistant.components.button import (
    ButtonDeviceClass,
    ButtonEntity,
    ButtonEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from hoymiles_wifi.dtu import DTU

from .const import (
    CONF_DTU_SERIAL_NUMBER,
    CONF_INVERTERS,
    CONF_THREE_PHASE_INVERTERS,
    DOMAIN,
    HASS_DTU,
)
from .entity import HoymilesEntity, HoymilesEntityDescription


@dataclass(frozen=True)
class HoymilesButtonEntityDescription(
    HoymilesEntityDescription, ButtonEntityDescription
):
    """Class to describe a Hoymiles Button entity."""

    action: str = ""


BUTTONS: tuple[HoymilesButtonEntityDescription, ...] = (
    HoymilesButtonEntityDescription(
        key="restart_dtu",
        translation_key="restart",
        device_class=ButtonDeviceClass.RESTART,
        is_dtu_sensor=True,
        action="async_restart_dtu",
    ),
    HoymilesButtonEntityDescription(
        key="turn_off_inverter_<inverter_serial>",
        translation_key="turn_off",
        icon="mdi:power-off",
        action="async_turn_off_inverter",
    ),
    HoymilesButtonEntityDescription(
        key="turn_on_inverter_<inverter_serial>",
        translation_key="turn_on",
        icon="mdi:power-on",
        action="async_turn_on_inverter",
    ),
    HoymilesButtonEntityDescription(
        key="enable_performance_data_mode",
        translation_key="enable_performance_data_mode",
        is_dtu_sensor=True,
        action="async_enable_performance_data_mode",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Hoymiles number entities."""
    hass_data = hass.data[DOMAIN][config_entry.entry_id]
    dtu = hass_data[HASS_DTU]
    dtu_serial_number = config_entry.data[CONF_DTU_SERIAL_NUMBER]
    single_phase_inverters = config_entry.data[CONF_INVERTERS]
    three_phase_inverters = config_entry.data.get(CONF_THREE_PHASE_INVERTERS, [])
    inverters = single_phase_inverters + three_phase_inverters

    buttons = []
    for description in BUTTONS:
        if description.is_dtu_sensor is True:
            updated_description = dataclasses.replace(
                description, serial_number=dtu_serial_number
            )
            buttons.append(HoymilesButtonEntity(config_entry, updated_description, dtu))
        else:
            for inverter_serial in inverters:
                new_key = description.key.replace("<inverter_serial>", inverter_serial)
                updated_description = dataclasses.replace(
                    description, key=new_key, serial_number=inverter_serial
                )
                buttons.append(
                    HoymilesButtonEntity(config_entry, updated_description, dtu)
                )

    async_add_entities(buttons)


class HoymilesButtonEntity(HoymilesEntity, ButtonEntity):
    """Hoymiles Number entity."""

    def __init__(
        self,
        config_entry: ConfigEntry,
        description: HoymilesButtonEntityDescription,
        dtu: DTU,
    ) -> None:
        """Initialize the HoymilesButtonEntity."""
        super().__init__(config_entry, description)
        self._dtu = dtu

    async def async_press(self) -> None:
        """Press the button."""

        if hasattr(self._dtu, self.entity_description.action) and callable(
            getattr(self._dtu, self.entity_description.action)
        ):
            method = getattr(self._dtu, self.entity_description.action)
            method_signature = signature(method)
            params = method_signature.parameters
            if "inverter_serial" in params:
                await method(self.entity_description.serial_number)
            else:
                await method()
        else:
            raise NotImplementedError(
                f"Method '{self.entity_description.action}' not implemented in DTU class."
            )
