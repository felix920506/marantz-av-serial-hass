"""Base entity for the Marantz AVR integration."""

from __future__ import annotations

from collections.abc import Callable, Iterable

from homeassistant.const import EntityCategory
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DOMAIN, MANUFACTURER
from .device import MarantzDevice
from .entity_defs import MAIN, ZONE2, ZONE3, SettingDef

ZONE_NAMES = {ZONE2: "Zone 2", ZONE3: "Zone 3"}


def device_info(device: MarantzDevice, zone: str = MAIN) -> DeviceInfo:
    """Return device info for a zone (zones are sub-devices)."""
    entry = device.entry
    main_id = (DOMAIN, entry.entry_id)
    if zone == MAIN:
        return DeviceInfo(
            identifiers={main_id},
            manufacturer=MANUFACTURER,
            model=device.model,
            name=entry.title,
            sw_version=device.firmware,
        )
    return DeviceInfo(
        identifiers={(DOMAIN, f"{entry.entry_id}_{zone}")},
        manufacturer=MANUFACTURER,
        model=device.model,
        name=f"{entry.title} {ZONE_NAMES[zone]}",
        via_device=main_id,
    )


def slugify_key(key: str) -> str:
    """Return a unique-id friendly version of a state key."""
    return "".join(c.lower() if c.isalnum() else "_" for c in key).strip("_")


class MarantzEntity(Entity):
    """Base entity; pushes state when any of its keys change."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, device: MarantzDevice, zone: str, keys: Iterable[str]) -> None:
        """Initialize."""
        self._device = device
        self._keys = tuple(keys)
        self._attr_device_info = device_info(device, zone)

    @property
    def available(self) -> bool:
        """Return if the receiver is connected."""
        return self._device.available

    async def async_added_to_hass(self) -> None:
        """Subscribe to updates."""
        self.async_on_remove(self._device.subscribe(self._keys, self._handle_update))
        self.async_on_remove(self._device.subscribe_availability(self._handle_update))

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()


class MarantzSettingEntity(MarantzEntity):
    """Entity backed by a single setting definition."""

    def __init__(self, device: MarantzDevice, definition: SettingDef) -> None:
        """Initialize."""
        super().__init__(device, definition.zone, (definition.key,))
        self._def = definition
        self._attr_name = definition.name
        self._attr_unique_id = f"{device.entry.entry_id}_{slugify_key(definition.key)}"
        self._attr_icon = definition.icon
        self._attr_entity_registry_enabled_default = definition.enabled_default
        if definition.config:
            self._attr_entity_category = EntityCategory.CONFIG

    @property
    def raw_value(self) -> str | None:
        """Return the raw state value."""
        return self._device.get(self._def.key)


def setup_dynamic_entities[T: SettingDef](
    device: MarantzDevice,
    definitions: Iterable[T],
    factory: Callable[[T], Entity],
    async_add_entities: Callable[[list[Entity]], None],
) -> Callable[[], None]:
    """Add entities for known keys now and for newly discovered keys later."""
    by_key = {d.key: d for d in definitions}
    added: set[str] = set()

    def _add(keys: Iterable[str]) -> None:
        new = [by_key[k] for k in keys if k in by_key and k not in added]
        if not new:
            return
        added.update(d.key for d in new)
        async_add_entities([factory(d) for d in new])

    _add([key for key in by_key if key in device.known_keys])

    @callback
    def _on_new(keys: set[str]) -> None:
        _add(keys)

    return device.subscribe_new_keys(_on_new)
