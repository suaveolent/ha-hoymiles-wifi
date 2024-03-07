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
from hoymiles_wifi.inverter import Inverter

from .const import CONF_DTU_SERIAL_NUMBER, DOMAIN, HASS_INVERTER
from .entity import HoymilesEntity


@dataclass(frozen=True)
class HoymilesButtonEntityDescription(ButtonEntityDescription):
    """Class to describe a Hoymiles Button entity."""

    is_dtu_sensor: bool = False
    serial_number: str = None



BUTTONS: tuple[HoymilesButtonEntityDescription, ...] = (
    HoymilesButtonEntityDescription(
        key="async_restart",
        translation_key="restart",
        device_class = ButtonDeviceClass.RESTART,
        is_dtu_sensor = True,
    ),
    HoymilesButtonEntityDescription(
        key="async_turn_off",
        translation_key="turn_off",
        icon="mdi:power-off",
        is_dtu_sensor = True,
    ),
    HoymilesButtonEntityDescription(
        key="async_turn_on",
        translation_key="turn_on",
        icon="mdi:power-on",
        is_dtu_sensor = True,
    ),
)

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Hoymiles number entities."""
    hass_data = hass.data[DOMAIN][entry.entry_id]
    inverter = hass_data[HASS_INVERTER]
    dtu_serial_number = entry.data[CONF_DTU_SERIAL_NUMBER]

    buttons = []
    for description in BUTTONS:
        updated_description = dataclasses.replace(description, serial_number=dtu_serial_number)
        buttons.append(HoymilesButtonEntity(entry, updated_description, inverter)
    )
    async_add_entities(buttons)


class HoymilesButtonEntity(HoymilesEntity, ButtonEntity):
    """Hoymiles Number entity."""

    def __init__(self, config_entry: ConfigEntry, description: HoymilesButtonEntityDescription, inverter: Inverter) -> None:
        """Initialize the HoymilesButtonEntity."""
        super().__init__(config_entry, description)
        self._inverter = inverter

    async def async_press(self) -> None:
        """Press the button."""

        if hasattr(self._inverter, self.entity_description.key) and callable(getattr(self._inverter, self.entity_description.key)):
            await getattr(self._inverter, self.entity_description.key)()
        else:
            raise NotImplementedError(f"Method '{self.entity_description.key}' not implemented in Inverter class.")



