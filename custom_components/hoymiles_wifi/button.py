"""Support for Hoymiles buttons."""

import dataclasses
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

from .const import CONF_DTU_SERIAL_NUMBER, CONF_INVERTERS, DOMAIN, HASS_DTU
from .entity import HoymilesEntity, HoymilesEntityDescription


@dataclass(frozen=True)
class HoymilesButtonEntityDescription(
    HoymilesEntityDescription, ButtonEntityDescription
):
    """Class to describe a Hoymiles Button entity."""


BUTTONS: tuple[HoymilesButtonEntityDescription, ...] = (
    HoymilesButtonEntityDescription(
        key="async_restart_dtu",
        translation_key="restart",
        device_class=ButtonDeviceClass.RESTART,
        is_dtu_sensor=True,
    ),
    HoymilesButtonEntityDescription(
        key="async_turn_off_inverter",
        translation_key="turn_off",
        icon="mdi:power-off",
    ),
    HoymilesButtonEntityDescription(
        key="async_turn_on_inverter",
        translation_key="turn_on",
        icon="mdi:power-on",
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
    inverters = config_entry.data[CONF_INVERTERS]

    buttons = []
    for description in BUTTONS:
        if description.is_dtu_sensor is True:
            updated_description = dataclasses.replace(
                description, serial_number=dtu_serial_number
            )
            buttons.append(HoymilesButtonEntity(config_entry, updated_description, dtu))
        else:
            for inverter_serial in inverters:
                updated_description = dataclasses.replace(
                    description, serial_number=inverter_serial
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

        if hasattr(self._inverter, self.entity_description.key) and callable(
            getattr(self._inverter, self.entity_description.key)
        ):
            await getattr(self._inverter, self.entity_description.key)()
        else:
            raise NotImplementedError(
                f"Method '{self.entity_description.key}' not implemented in Inverter class."
            )
