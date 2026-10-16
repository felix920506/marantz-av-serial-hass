"""Media player entities for the main zone and zones 2/3."""

from __future__ import annotations

from typing import Any

from homeassistant.components.media_player import (
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import MarantzConfigEntry
from .const import DOMAIN, SOUND_MODES, SOURCE_ALIASES, ZONE_FOLLOW_MAIN
from .device import MarantzDevice
from .entity import MarantzEntity
from .entity_defs import MAIN, ZONE2, ZONE3, _tuner_frequency
from .protocol import decode_volume, encode_volume

MAX_VOLUME = 98.0
ZERO_DB = 80.0

ZONE_FEATURES = (
    MediaPlayerEntityFeature.TURN_ON
    | MediaPlayerEntityFeature.TURN_OFF
    | MediaPlayerEntityFeature.VOLUME_SET
    | MediaPlayerEntityFeature.VOLUME_STEP
    | MediaPlayerEntityFeature.VOLUME_MUTE
    | MediaPlayerEntityFeature.SELECT_SOURCE
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MarantzConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up media players."""
    device = entry.runtime_data
    entities: list[MarantzZone] = [MarantzMainZone(device)]
    added: set[str] = set()

    def _zones(keys: set[str]) -> list[MarantzZone]:
        new: list[MarantzZone] = []
        for zone, prefix in ((ZONE2, "Z2"), (ZONE3, "Z3")):
            if f"{prefix}PW" in keys and zone not in added:
                added.add(zone)
                new.append(MarantzZone(device, zone, prefix))
        return new

    entities.extend(_zones(device.known_keys))
    async_add_entities(entities)

    @callback
    def _on_new(keys: set[str]) -> None:
        if new := _zones(keys):
            async_add_entities(new)

    entry.async_on_unload(device.subscribe_new_keys(_on_new))


class MarantzZone(MarantzEntity, MediaPlayerEntity):
    """A zone of the receiver."""

    _attr_device_class = MediaPlayerDeviceClass.RECEIVER
    _attr_supported_features = ZONE_FEATURES
    # Secondary zones only accept whole steps; the main zone accepts 0.5.
    _attr_volume_step = 1 / MAX_VOLUME
    _volume_resolution = 1.0

    def __init__(self, device: MarantzDevice, zone: str, prefix: str) -> None:
        """Initialize a secondary zone (prefix Z2/Z3)."""
        self._prefix = prefix
        self._power_key = f"{prefix}PW"
        self._volume_key = f"{prefix}MV"
        self._mute_key = f"{prefix}MU"
        self._source_key = f"{prefix}SI"
        super().__init__(
            device,
            zone,
            (
                self._power_key,
                self._volume_key,
                self._mute_key,
                self._source_key,
                "MVMAX",
                "TFAN",
                "SI",
            ),
        )
        self._attr_unique_id = f"{device.entry.entry_id}_{zone}"
        self._attr_name = None

    # -- commands (overridden by the main zone) -----------------------------

    def _cmd_power(self, on: bool) -> str:
        return f"{self._prefix}{'ON' if on else 'OFF'}"

    def _cmd_volume(self, raw: str) -> str:
        return f"{self._prefix}{raw}"

    def _cmd_mute(self, on: bool) -> str:
        return f"{self._prefix}MU{'ON' if on else 'OFF'}"

    def _cmd_source(self, code: str) -> str:
        return f"{self._prefix}{code}"

    # -- state --------------------------------------------------------------

    @property
    def state(self) -> MediaPlayerState | None:
        """Return the power state."""
        power = self._device.get(self._power_key)
        if power is None:
            return None
        return MediaPlayerState.ON if power == "ON" else MediaPlayerState.OFF

    @property
    def _volume_abs(self) -> float | None:
        raw = self._device.get(self._volume_key)
        return decode_volume(raw) if raw is not None else None

    @property
    def volume_level(self) -> float | None:
        """Return volume level 0..1 (maps to the 0..98 display scale)."""
        if (volume := self._volume_abs) is None:
            return None
        return volume / MAX_VOLUME

    @property
    def is_volume_muted(self) -> bool | None:
        """Return mute state."""
        mute = self._device.get(self._mute_key)
        return None if mute is None else mute == "ON"

    @property
    def _current_source_code(self) -> str | None:
        code = self._device.get(self._source_key)
        if code is None:
            return None
        return SOURCE_ALIASES.get(code, code)

    @property
    def source(self) -> str | None:
        """Return the current source name."""
        code = self._current_source_code
        if code is None:
            return None
        if code == ZONE_FOLLOW_MAIN:
            return "Main zone source"
        return self._device.source_name(code)

    @property
    def source_list(self) -> list[str]:
        """Return the selectable sources."""
        names = [
            self._device.source_name(code) for code in self._device.enabled_sources()
        ]
        return ["Main zone source", *names]

    def _source_code(self, name: str) -> str:
        if name == "Main zone source":
            return ZONE_FOLLOW_MAIN
        for code in self._device.enabled_sources():
            if self._device.source_name(code) == name:
                return code
        # Allow raw codes as well (e.g. from automations).
        upper = name.upper()
        if upper in {c for c in self._device.enabled_sources()}:
            return upper
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="invalid_source",
            translation_placeholders={"source": name},
        )

    @property
    def media_content_type(self) -> MediaType | None:
        """Return the content type."""
        return MediaType.MUSIC if self.state == MediaPlayerState.ON else None

    @property
    def media_title(self) -> str | None:
        """Return the tuner frequency when listening to the tuner."""
        if self.state != MediaPlayerState.ON:
            return None
        code = self._current_source_code
        if code == ZONE_FOLLOW_MAIN:
            code = self._device.get("SI")
        if code == "TUNER" and (freq := self._device.get("TFAN")):
            return _tuner_frequency(freq)
        return self.source

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra attributes."""
        attrs: dict[str, Any] = {}
        if (volume := self._volume_abs) is not None:
            attrs["volume_db"] = None if volume == 0 else volume - ZERO_DB
            attrs["volume_display"] = volume
        return attrs

    # -- actions ------------------------------------------------------------

    async def async_turn_on(self) -> None:
        """Turn the zone on."""
        await self._device.async_send(self._cmd_power(True))

    async def async_turn_off(self) -> None:
        """Turn the zone off."""
        await self._device.async_send(self._cmd_power(False))

    async def async_set_volume_level(self, volume: float) -> None:
        """Set volume (0..1 maps to 0..98)."""
        maximum = MAX_VOLUME
        if (raw_max := self._device.get("MVMAX")) and (
            decoded := decode_volume(raw_max)
        ) is not None:
            maximum = decoded
        target = round(volume * MAX_VOLUME / self._volume_resolution)
        await self._device.async_send(
            self._cmd_volume(encode_volume(target * self._volume_resolution, maximum))
        )

    async def async_volume_up(self) -> None:
        """Volume up one step."""
        await self._device.async_send(self._cmd_volume("UP"))

    async def async_volume_down(self) -> None:
        """Volume down one step."""
        await self._device.async_send(self._cmd_volume("DOWN"))

    async def async_mute_volume(self, mute: bool) -> None:
        """Mute or unmute."""
        await self._device.async_send(self._cmd_mute(mute))

    async def async_select_source(self, source: str) -> None:
        """Select an input source."""
        await self._device.async_send(self._cmd_source(self._source_code(source)))


class MarantzMainZone(MarantzZone):
    """The main zone."""

    _attr_supported_features = (
        ZONE_FEATURES | MediaPlayerEntityFeature.SELECT_SOUND_MODE
    )
    _attr_sound_mode_list = SOUND_MODES
    _attr_volume_step = 0.5 / MAX_VOLUME
    _volume_resolution = 0.5

    def __init__(self, device: MarantzDevice) -> None:
        """Initialize the main zone."""
        super().__init__(device, MAIN, "")
        self._power_key = "ZM"
        self._volume_key = "MV"
        self._mute_key = "MU"
        self._source_key = "SI"
        self._keys = ("ZM", "MV", "MU", "SI", "MS", "MVMAX", "TFAN", "SYSMI", "SYSDA")

    def _cmd_power(self, on: bool) -> str:
        return "ZMON" if on else "ZMOFF"

    def _cmd_volume(self, raw: str) -> str:
        return f"MV{raw}"

    def _cmd_mute(self, on: bool) -> str:
        return "MUON" if on else "MUOFF"

    def _cmd_source(self, code: str) -> str:
        return f"SI{code}"

    @property
    def source_list(self) -> list[str]:
        """Return the selectable sources."""
        return [
            self._device.source_name(code) for code in self._device.enabled_sources()
        ]

    @property
    def sound_mode(self) -> str | None:
        """Return the current surround mode."""
        return self._device.get("MS")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra attributes."""
        attrs = super().extra_state_attributes
        if sound_mode := self._device.get("SYSMI"):
            attrs["sound_mode_display"] = sound_mode
        if audio := self._device.get("SYSDA"):
            attrs["audio_signal"] = audio
        return attrs

    async def async_select_sound_mode(self, sound_mode: str) -> None:
        """Select a surround mode."""
        await self._device.async_send(f"MS{sound_mode.upper()}")
