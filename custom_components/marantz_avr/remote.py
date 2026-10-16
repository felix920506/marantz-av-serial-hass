"""Remote entity: menu navigation and raw protocol commands."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from typing import Any

from homeassistant.components.remote import (
    ATTR_DELAY_SECS,
    ATTR_NUM_REPEATS,
    DEFAULT_DELAY_SECS,
    RemoteEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import MarantzConfigEntry
from .device import MarantzDevice
from .entity import MarantzEntity
from .entity_defs import MAIN

# Friendly command names -> protocol commands.  Anything else is sent as-is,
# so raw protocol commands (e.g. "PSDYNEQ ON") also work.
COMMANDS: dict[str, str] = {
    "up": "MNCUP",
    "down": "MNCDN",
    "left": "MNCLT",
    "right": "MNCRT",
    "enter": "MNENT",
    "select": "MNENT",
    "back": "MNRTN",
    "return": "MNRTN",
    "menu": "MNMEN ON",
    "menu_on": "MNMEN ON",
    "menu_off": "MNMEN OFF",
    "option": "MNOPT",
    "info": "MNINF",
    "channel_level": "MNCHL",
    "volume_up": "MVUP",
    "volume_down": "MVDOWN",
    "mute": "MUON",
    "unmute": "MUOFF",
    "next_sound_mode": "MSRIGHT",
    "previous_sound_mode": "MSLEFT",
    "dimmer": "DIM SEL",
    "tuner_preset_up": "TPANUP",
    "tuner_preset_down": "TPANDOWN",
    "tuner_up": "TFANUP",
    "tuner_down": "TFANDOWN",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MarantzConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the remote."""
    async_add_entities([MarantzRemote(entry.runtime_data)])


class MarantzRemote(MarantzEntity, RemoteEntity):
    """Remote for the receiver; on/off controls system power (all zones)."""

    _attr_name = None

    def __init__(self, device: MarantzDevice) -> None:
        """Initialize."""
        super().__init__(device, MAIN, ("PW",))
        self._attr_unique_id = f"{device.entry.entry_id}_remote"

    @property
    def is_on(self) -> bool | None:
        """Return system power state."""
        power = self._device.get("PW")
        return None if power is None else power == "ON"

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Power on the whole system."""
        await self._device.async_send("PWON")

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Put the whole system in standby."""
        await self._device.async_send("PWSTANDBY")

    async def async_send_command(self, command: Iterable[str], **kwargs: Any) -> None:
        """Send named or raw commands."""
        repeats = kwargs.get(ATTR_NUM_REPEATS, 1)
        delay = kwargs.get(ATTR_DELAY_SECS, DEFAULT_DELAY_SECS)
        commands = list(command)
        for i in range(repeats):
            for j, cmd in enumerate(commands):
                await self._device.async_send(COMMANDS.get(cmd.lower(), cmd))
                if delay and (i < repeats - 1 or j < len(commands) - 1):
                    await asyncio.sleep(delay)
