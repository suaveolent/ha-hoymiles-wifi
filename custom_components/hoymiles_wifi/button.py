"""Support for Hoymiles buttons."""

from dataclasses import dataclass

from homeassistant.components.button import (
    ButtonDeviceClass,
    ButtonEntity,
    ButtonEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
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

def get_hoymiles_unique_id(config_entry_id: str, key: str) -> str:
    """Create a _unique_id id for a Hoymiles entity."""
    return f"hoymiles_{config_entry_id}_{key}"

class HoymilesButtonEntity(HoymilesEntity, ButtonEntity):
    """Hoymiles Number entity."""

    def __init__(self, config_entry: ConfigEntry, description: HoymilesButtonEntityDescription, inverter: Inverter) -> None:
        """Initialize the HoymilesButtonEntity."""
        super().__init__(config_entry)
        self._inverter = inverter
        self.entity_description = description
        self._attr_unique_id = get_hoymiles_unique_id(config_entry.entry_id, description.key)

    def press(self) -> None:
        """Press the button."""

        if hasattr(self._inverter, self.entity_description.key) and callable(getattr(self._inverter, self.entity_description.key)):
            # Call the method dynamically
            getattr(self._inverter, self.entity_description.ke)()
        else:
            # Handle the case when the key does not correspond to a valid method
            raise NotImplementedError(f"Method '{self.entity_description.ke}' not implemented in Inverter class.")



