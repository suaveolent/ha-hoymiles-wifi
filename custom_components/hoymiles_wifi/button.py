"""Support for Hoymiles buttons."""

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

from .const import DOMAIN, HASS_INVERTER
from .entity import HoymilesEntity


@dataclass(frozen=True)
class HoymilesButtonEntityDescription(ButtonEntityDescription):
    """Class to describe a Hoymiles Button entity."""

BUTTONS: tuple[HoymilesButtonEntityDescription, ...] = (
    HoymilesButtonEntityDescription(
        key="restart",
        translation_key="restart",
        device_class = ButtonDeviceClass.RESTART
    ),
    HoymilesButtonEntityDescription(
        key="turn_off",
        translation_key="turn_off",
        icon="mdi:power-off",
    ),
    HoymilesButtonEntityDescription(
        key="turn_on",
        translation_key="turn_on",
        icon="mdi:power-on",
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
    async_add_entities(
        HoymilesButtonEntity(entry, data, inverter) for data in BUTTONS
    )

class HoymilesButtonEntity(HoymilesEntity, ButtonEntity):
    """Hoymiles Number entity."""

    def __init__(self, config_entry: ConfigEntry, description: HoymilesButtonEntityDescription, inverter: Inverter) -> None:
        """Initialize the HoymilesButtonEntity."""
        super().__init__(config_entry, description)
        self._inverter = inverter

    def press(self) -> None:
        """Press the button."""

        if hasattr(self._inverter, self.entity_description.key) and callable(getattr(self._inverter, self.entity_description.key)):
            getattr(self._inverter, self.entity_description.key)()
        else:
            raise NotImplementedError(f"Method '{self.entity_description.key}' not implemented in Inverter class.")



