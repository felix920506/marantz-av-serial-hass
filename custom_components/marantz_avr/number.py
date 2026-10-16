"""Number entities for receiver settings."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import MarantzConfigEntry
from .entity import MarantzSettingEntity, setup_dynamic_entities
from .entity_defs import NUMBERS, NumberDef


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MarantzConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up number entities."""
    device = entry.runtime_data
    entry.async_on_unload(
        setup_dynamic_entities(
            device,
            NUMBERS,
            lambda d: MarantzNumber(device, d),
            async_add_entities,
        )
    )


class MarantzNumber(MarantzSettingEntity, NumberEntity):
    """A numeric setting."""

    _def: NumberDef
    _attr_mode = NumberMode.BOX

    def __init__(self, device, definition: NumberDef) -> None:
        """Initialize."""
        super().__init__(device, definition)
        self._attr_native_min_value = definition.min_value
        self._attr_native_max_value = definition.max_value
        self._attr_native_step = definition.step
        self._attr_native_unit_of_measurement = definition.unit

    @property
    def native_value(self) -> float | None:
        """Return the value."""
        raw = self.raw_value
        if raw is None:
            return None
        return self._def.decode(raw)

    async def async_set_native_value(self, value: float) -> None:
        """Set the value."""
        if value == 0 and self._def.zero_command:
            command = self._def.zero_command
        else:
            command = self._def.command.format(self._def.encode(value))
        await self._device.async_send(command)
