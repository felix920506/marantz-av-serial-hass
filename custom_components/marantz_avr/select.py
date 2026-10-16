"""Select entities for receiver settings."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import MarantzConfigEntry
from .entity import MarantzSettingEntity, setup_dynamic_entities
from .entity_defs import SELECTS, SelectDef


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MarantzConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up select entities."""
    device = entry.runtime_data
    entry.async_on_unload(
        setup_dynamic_entities(
            device,
            SELECTS,
            lambda d: MarantzSelect(device, d),
            async_add_entities,
        )
    )


class MarantzSelect(MarantzSettingEntity, SelectEntity):
    """A setting with a fixed list of values."""

    _def: SelectDef

    def __init__(self, device, definition: SelectDef) -> None:
        """Initialize."""
        super().__init__(device, definition)
        self._attr_options = list(definition.options.values())

    @property
    def current_option(self) -> str | None:
        """Return the current option."""
        raw = self.raw_value
        if raw is None:
            return None
        return self._def.options.get(raw)

    async def async_select_option(self, option: str) -> None:
        """Change the setting."""
        raw = next(k for k, v in self._def.options.items() if v == option)
        await self._device.async_send(self._def.command.format(raw))
