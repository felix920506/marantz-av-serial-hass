"""Sensor entities for signal information."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import MarantzConfigEntry
from .entity import MarantzSettingEntity, setup_dynamic_entities
from .entity_defs import SENSORS, SensorDef


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MarantzConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up sensor entities."""
    device = entry.runtime_data
    entry.async_on_unload(
        setup_dynamic_entities(
            device,
            SENSORS,
            lambda d: MarantzSensor(device, d),
            async_add_entities,
        )
    )


class MarantzSensor(MarantzSettingEntity, SensorEntity):
    """A read-only value reported by the receiver."""

    _def: SensorDef
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self) -> str | None:
        """Return the value."""
        raw = self.raw_value
        if raw is None:
            return None
        if self._def.transform is not None:
            return self._def.transform(raw)
        return raw.strip() or None
