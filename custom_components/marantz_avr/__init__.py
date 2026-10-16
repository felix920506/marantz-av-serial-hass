"""The Marantz AVR (RS-232C / IP) integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .const import (
    CONF_CONNECTION_TYPE,
    CONF_SERIAL_URL,
    CONNECTION_SERIAL,
    DEFAULT_NETWORK_PORT,
    DOMAIN,
)
from .device import MarantzDevice
from .protocol import (
    MarantzClient,
    MarantzConnectionError,
    Opener,
    serial_opener,
    tcp_opener,
)

PLATFORMS: list[Platform] = [
    Platform.MEDIA_PLAYER,
    Platform.NUMBER,
    Platform.REMOTE,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]

type MarantzConfigEntry = ConfigEntry[MarantzDevice]


def opener_from_config(data: dict) -> Opener:
    """Build a transport opener from config entry data."""
    if data.get(CONF_CONNECTION_TYPE) == CONNECTION_SERIAL:
        return serial_opener(data[CONF_SERIAL_URL])
    return tcp_opener(data[CONF_HOST], data.get(CONF_PORT, DEFAULT_NETWORK_PORT))


async def async_setup_entry(hass: HomeAssistant, entry: MarantzConfigEntry) -> bool:
    """Set up a receiver from a config entry."""
    client = MarantzClient(opener_from_config(dict(entry.data)))
    device = MarantzDevice(hass, entry, client)
    await device.async_load()
    try:
        await device.async_start()
    except MarantzConnectionError as err:
        await device.async_stop()
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="cannot_connect",
            translation_placeholders={"error": str(err)},
        ) from err

    entry.runtime_data = device
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: MarantzConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        await entry.runtime_data.async_stop()
    return unload_ok


async def async_remove_entry(hass: HomeAssistant, entry: MarantzConfigEntry) -> None:
    """Remove persisted data when the entry is deleted."""
    from homeassistant.helpers.storage import Store  # noqa: PLC0415

    await Store(hass, 1, f"{DOMAIN}.{entry.entry_id}").async_remove()


async def _async_update_listener(
    hass: HomeAssistant, entry: MarantzConfigEntry
) -> None:
    """Reload when options change."""
    await hass.config_entries.async_reload(entry.entry_id)
