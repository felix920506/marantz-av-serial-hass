"""Switch entities for receiver settings."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import MarantzConfigEntry
from .entity import MarantzSettingEntity, setup_dynamic_entities
from .entity_defs import SWITCHES, SwitchDef


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MarantzConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up switch entities."""
    device = entry.runtime_data
    entry.async_on_unload(
        setup_dynamic_entities(
            device,
            SWITCHES,
            lambda d: MarantzSwitch(device, d),
            async_add_entities,
        )
    )


class MarantzSwitch(MarantzSettingEntity, SwitchEntity):
    """An on/off setting."""

    _def: SwitchDef

    @property
    def is_on(self) -> bool | None:
        """Return the state."""
        raw = self.raw_value
        if raw is None:
            return None
        return raw == self._def.on_value

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on."""
        await self._device.async_send(self._def.on_command)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off."""
        await self._device.async_send(self._def.off_command)
