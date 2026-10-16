"""Home Assistant side wrapper around the protocol client."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import contextlib
from datetime import timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_call_later, async_track_time_interval
from homeassistant.helpers.storage import Store

from .const import (
    BASE_QUERIES,
    CONF_SOURCES,
    DOMAIN,
    INFO_POLL_INTERVAL,
    INFO_QUERIES,
    OPTIONAL_SOURCES,
    SOURCE_ALIASES,
    SOURCES,
)
from .entity_defs import all_queries
from .protocol import MarantzClient, Update

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
# Keys whose presence is persisted so entities exist even if the receiver
# can't be queried at startup.
_PERSISTED_PREFIXES = ("SSFUN:", "SSSOD:")


class MarantzDevice:
    """Owns the client, the persisted capabilities and dispatching."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, client: MarantzClient
    ) -> None:
        """Initialize."""
        self.hass = hass
        self.entry = entry
        self.client = client
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}"
        )
        self.known_keys: set[str] = set()
        self._persisted: dict[str, str] = {}
        self._key_listeners: dict[str, list[Callable[[], None]]] = {}
        self._availability_listeners: list[Callable[[], None]] = []
        self._new_key_listeners: list[Callable[[set[str]], None]] = []
        self._unsubs: list[CALLBACK_TYPE] = []
        self._initial_refresh = asyncio.Event()
        self._refresh_task: asyncio.Task[None] | None = None
        self._info_unsub: CALLBACK_TYPE | None = None
        self._full_refresh_unsub: CALLBACK_TYPE | None = None
        self._main_power: str | None = None

    # -- lifecycle ----------------------------------------------------------

    async def async_load(self) -> None:
        """Load persisted capabilities."""
        data = await self._store.async_load() or {}
        self.known_keys = set(data.get("known_keys", []))
        self._persisted = dict(data.get("persisted", {}))
        for key, value in self._persisted.items():
            self.client.state.setdefault(key, value)

    async def async_start(self) -> None:
        """Connect and run the initial refresh."""
        self._unsubs.append(self.client.add_update_callback(self._handle_updates))
        self._unsubs.append(
            self.client.add_connection_callback(self._handle_connection)
        )
        self._unsubs.append(self.client.add_connect_handler(self._on_connect))
        first_run = not self.known_keys
        await self.client.start()
        if first_run:
            # Nothing cached yet: wait for the refresh so that every supported
            # setting gets an entity right away.  Afterwards the cache is used
            # and the refresh completes in the background.
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._initial_refresh.wait(), 120)
        self._unsubs.append(
            async_track_time_interval(
                self.hass,
                self._poll_info,
                timedelta(seconds=INFO_POLL_INTERVAL),
                cancel_on_shutdown=True,
            )
        )

    async def async_stop(self) -> None:
        """Disconnect."""
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        for attr in ("_info_unsub", "_full_refresh_unsub"):
            if (unsub := getattr(self, attr)) is not None:
                unsub()
                setattr(self, attr, None)
        if self._refresh_task is not None:
            self._refresh_task.cancel()
        await self.client.stop()
        await self._async_save()

    # -- state helpers ------------------------------------------------------

    @property
    def available(self) -> bool:
        """Return if the receiver is reachable."""
        return self.client.connected

    def get(self, key: str) -> str | None:
        """Return a raw state value."""
        return self.client.state.get(key)

    @property
    def model(self) -> str | None:
        """Return the model name (e.g. ``CINEMA 40``)."""
        model = self.get("SYMO")
        if not model:
            return None
        # SYMO includes the region suffix, e.g. "CINEMA 40USA".
        for suffix in ("USA", "EUR", "JPN", "CHN", "AUS", "UK", "E2", "E3"):
            if model.endswith(suffix):
                return model[: -len(suffix)].strip()
        return model

    @property
    def friendly_name(self) -> str | None:
        """Return the friendly name configured on the receiver."""
        return self.get("NSFRN")

    @property
    def firmware(self) -> str | None:
        """Return the firmware version."""
        return self.get("SSINFFRMAVR")

    # -- sources ------------------------------------------------------------

    def source_name(self, code: str) -> str:
        """Return the display name for a source code."""
        code = SOURCE_ALIASES.get(code, code)
        if name := self.get(f"SSFUN:{code}"):
            return name
        return SOURCES.get(code, code)

    def default_sources(self) -> list[str]:
        """Return the source codes enabled by default."""
        if any(key.startswith("SSSOD:") for key in self.client.state):
            used = [
                code
                for code in SOURCES
                if self.get(f"SSSOD:{code}") in (None, "USE")
                and (code not in OPTIONAL_SOURCES or self.get(f"SSSOD:{code}"))
            ]
            return used
        if self.model == "AV 10":
            return list(SOURCES)
        return [code for code in SOURCES if code not in OPTIONAL_SOURCES]

    def enabled_sources(self) -> list[str]:
        """Return the source codes selected by the user (or the defaults)."""
        selected = self.entry.options.get(CONF_SOURCES)
        if selected:
            return [code for code in SOURCES if code in selected]
        return self.default_sources()

    # -- commands -----------------------------------------------------------

    async def async_send(self, *commands: str) -> None:
        """Send commands, raising if the receiver isn't connected."""
        if not self.client.connected:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="not_connected"
            )
        await self.client.send(*commands)

    # -- subscriptions ------------------------------------------------------

    @callback
    def subscribe(
        self, keys: tuple[str, ...] | list[str], listener: Callable[[], None]
    ) -> CALLBACK_TYPE:
        """Call ``listener`` when any of ``keys`` changes."""
        for key in keys:
            self._key_listeners.setdefault(key, []).append(listener)

        @callback
        def _unsub() -> None:
            for key in keys:
                with contextlib.suppress(ValueError, KeyError):
                    self._key_listeners[key].remove(listener)

        return _unsub

    @callback
    def subscribe_availability(self, listener: Callable[[], None]) -> CALLBACK_TYPE:
        """Call ``listener`` when the connection state changes."""
        self._availability_listeners.append(listener)
        return lambda: self._availability_listeners.remove(listener)

    @callback
    def subscribe_new_keys(self, listener: Callable[[set[str]], None]) -> CALLBACK_TYPE:
        """Call ``listener`` with keys seen for the first time."""
        self._new_key_listeners.append(listener)
        return lambda: self._new_key_listeners.remove(listener)

    @callback
    def _handle_updates(self, updates: list[Update]) -> None:
        new_keys: set[str] = set()
        notified: set[int] = set()
        for update in updates:
            if update.key not in self.known_keys:
                self.known_keys.add(update.key)
                new_keys.add(update.key)
            if update.key.startswith(_PERSISTED_PREFIXES):
                self._persisted[update.key] = update.value
            for listener in self._key_listeners.get(update.key, ()):
                if id(listener) not in notified:
                    notified.add(id(listener))
                    listener()
            if update.key in ("SI", "MS", "ZM"):
                self._schedule_info_poll()
            if update.key == "ZM":
                # Settings may have changed while the zone was off.
                if update.value == "ON" and self._main_power == "OFF":
                    self._schedule_full_refresh()
                self._main_power = update.value
        if new_keys:
            self._schedule_save()
            for listener in list(self._new_key_listeners):
                listener(new_keys)

    @callback
    def _handle_connection(self, connected: bool) -> None:
        for listener in list(self._availability_listeners):
            listener()

    # -- refresh ------------------------------------------------------------

    async def _on_connect(self) -> None:
        """Refresh everything after (re)connecting."""
        if self._refresh_task is not None and not self._refresh_task.done():
            self._refresh_task.cancel()
        self._refresh_task = self.entry.async_create_background_task(
            self.hass, self._async_full_refresh(), "marantz_avr refresh"
        )

    async def _async_full_refresh(self) -> None:
        queries = list(dict.fromkeys([*BASE_QUERIES, *all_queries(), *INFO_QUERIES]))
        await self.client.query(queries)
        try:
            await asyncio.wait_for(self.client.drain(), 120)
            await asyncio.sleep(0.5)  # responses arrive within 200 ms
        except TimeoutError:
            _LOGGER.debug("Status refresh did not complete")
        self._initial_refresh.set()
        await self._async_save()

    @callback
    def _schedule_full_refresh(self) -> None:
        if self._full_refresh_unsub is not None:
            self._full_refresh_unsub()

        @callback
        def _run(_now: Any) -> None:
            self._full_refresh_unsub = None
            self.hass.async_create_task(self._on_connect())

        self._full_refresh_unsub = async_call_later(self.hass, 3, _run)

    @callback
    def _schedule_info_poll(self) -> None:
        if self._info_unsub is not None:
            self._info_unsub()

        @callback
        def _run(_now: Any) -> None:
            self._info_unsub = None
            self.hass.async_create_task(self._poll_info())

        self._info_unsub = async_call_later(self.hass, 3, _run)

    async def _poll_info(self, _now: Any = None) -> None:
        if self.client.connected and self.get("ZM") == "ON":
            await self.client.query(INFO_QUERIES)

    # -- persistence --------------------------------------------------------

    @callback
    def _schedule_save(self) -> None:
        self._store.async_delay_save(self._data_to_save, 10)

    def _data_to_save(self) -> dict[str, Any]:
        return {
            "known_keys": sorted(self.known_keys),
            "persisted": self._persisted,
        }

    async def _async_save(self) -> None:
        await self._store.async_save(self._data_to_save())
