"""Support for Hoymiles number sensors."""

import dataclasses
from dataclasses import dataclass
from enum import Enum
import logging

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_DTU_SERIAL_NUMBER,
    CONF_INVERTERS,
    CONF_THREE_PHASE_INVERTERS,
    DOMAIN,
    HASS_CONFIG_COORDINATOR,
    HASS_DATA_COORDINATOR,
)
from .entity import HoymilesCoordinatorEntity, HoymilesEntityDescription

from hoymiles_wifi.const import MAX_POWER_LIMIT
from hoymiles_wifi.hoymiles import DTUType, get_dtu_model_type


class SetAction(Enum):
    """Enum for set actions."""

    POWER_LIMIT = 1


@dataclass(frozen=True)
class HoymilesNumberSensorEntityDescriptionMixin:
    """Mixin for required keys."""


@dataclass(frozen=True)
class HoymilesNumberSensorEntityDescription(
    HoymilesEntityDescription, NumberEntityDescription
):
    """Describes Hoymiles number sensor entity."""

    set_action: SetAction = None
    conversion_factor: float = None
    serial_number: str = None
    is_dtu_sensor: bool = False


CONFIG_CONTROL_ENTITIES = (
    HoymilesNumberSensorEntityDescription(
        key="limit_power_mypower",
        translation_key="limit_power_mypower",
        mode=NumberMode.SLIDER,
        device_class=NumberDeviceClass.POWER_FACTOR,
        set_action=SetAction.POWER_LIMIT,
        conversion_factor=0.1,
        is_dtu_sensor=True,
    ),
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Hoymiles number entities."""
    hass_data = hass.data[DOMAIN][config_entry.entry_id]
    config_coordinator = hass_data.get(HASS_CONFIG_COORDINATOR, None)
    data_coordinator = hass_data.get(HASS_DATA_COORDINATOR, None)
    single_phase_inverters = config_entry.data.get(CONF_INVERTERS, [])
    three_phase_inverters = config_entry.data.get(CONF_THREE_PHASE_INVERTERS, [])
    dtu_serial_number = config_entry.data[CONF_DTU_SERIAL_NUMBER]

    if single_phase_inverters or three_phase_inverters:
        sensors = []
        for description in CONFIG_CONTROL_ENTITIES:
            if description.is_dtu_sensor is True:
                updated_description = dataclasses.replace(
                    description, serial_number=dtu_serial_number
                )
                sensors.append(
                    HoymilesNumberEntity(
                        config_entry,
                        updated_description,
                        # Real data is the primary source: newer DTU firmware no
                        # longer answers get_config, but still reports the limit
                        # per inverter in the real data response. The config
                        # coordinator stays as a fallback for firmware that only
                        # exposes it there.
                        data_coordinator or config_coordinator,
                        fallback_coordinator=config_coordinator,
                    )
                )
        async_add_entities(sensors)


class HoymilesNumberEntity(HoymilesCoordinatorEntity, NumberEntity):
    """Hoymiles Number entity."""

    def __init__(
        self,
        config_entry: ConfigEntry,
        description: HoymilesNumberSensorEntityDescription,
        coordinator: HoymilesCoordinatorEntity,
        fallback_coordinator: HoymilesCoordinatorEntity = None,
    ) -> None:
        """Initialize the HoymilesNumberEntity."""
        super().__init__(config_entry, description, coordinator)
        self._attribute_name = description.key
        self._conversion_factor = description.conversion_factor
        self._set_action = description.set_action
        self._fallback_coordinator = fallback_coordinator
        self._native_value = None
        self._assumed_state = False

        self.update_state_value()

    async def async_added_to_hass(self) -> None:
        """Subscribe to the fallback coordinator in addition to the primary.

        On firmware that only reports the limit via ``get_config``, the value
        comes from the fallback coordinator. Without its own subscription the
        entity would not pick that up until the next real data tick.
        """
        await super().async_added_to_hass()

        if self._fallback_coordinator is not None:
            self.async_on_remove(
                self._fallback_coordinator.async_add_listener(
                    self._handle_coordinator_update
                )
            )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.update_state_value()
        super()._handle_coordinator_update()

    @property
    def native_value(self) -> float:
        """Get the native value of the entity."""
        return self._native_value

    @property
    def assumed_state(self):
        """Return the assumed state of the entity."""
        return self._assumed_state

    async def async_set_native_value(self, value: float) -> None:
        """Set the native value of the entity.

        Args:
            value (float): The value to set.
        """
        if self._set_action == SetAction.POWER_LIMIT:
            dtu = self.coordinator.get_dtu()
            if value < 0 or value > MAX_POWER_LIMIT:
                _LOGGER.error(
                    "Power limit %s out of range (0-%s)", value, MAX_POWER_LIMIT
                )
                return
            await dtu.async_set_power_limit(value)
            await self.coordinator.async_request_refresh()
        else:
            _LOGGER.error("Invalid set action!")
            return

        self._assumed_state = True
        self._native_value = value

    def _resolve_raw_power_limit(self) -> int | None:
        """Read the raw power limit from whichever source reports it.

        Preferred source is the real data response, which reports ``power_limit``
        per single phase inverter. Newer DTU firmware stops answering
        ``get_config`` entirely, so that is the only place the limit survives.
        Older firmware is covered by the ``get_config`` fallback.
        """
        data = getattr(self.coordinator, "data", None)
        sgs_data = getattr(data, "sgs_data", None)
        if sgs_data:
            # A power limit command applies to the whole DTU, so every inverter
            # reports the same value. Take the first that reports one.
            for sgs in sgs_data:
                raw = getattr(sgs, "power_limit", None)
                if raw:
                    return raw

        fallback = getattr(self._fallback_coordinator, "data", None)
        if fallback is not None:
            return getattr(fallback, "limit_power_mypower", None)

        # Real data was available but reported no limit, which is how an
        # unconfigured DTU looks. Distinguish that from "no data at all".
        return 0 if sgs_data else None

    def update_state_value(self):
        """Update the state value of the entity."""
        raw = self._resolve_raw_power_limit()

        self._assumed_state = False

        if raw is None:
            self._native_value = None
            return

        if raw == 0:
            # 0 is not a settable limit: the DTU reports it when no limit is
            # stored, which means the inverter is running unrestricted.
            self._native_value = float(MAX_POWER_LIMIT)
            return

        self._native_value = (
            raw * self._conversion_factor if self._conversion_factor else raw
        )
