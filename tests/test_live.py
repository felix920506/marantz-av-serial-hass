"""Live tests against a real receiver.

Skipped unless MARANTZ_LIVE_HOST (telnet) and/or MARANTZ_LIVE_SERIAL_URL
(e.g. socket://192.168.1.10:4001) are set.  The tests change a few harmless
settings and restore them afterwards.
"""

from __future__ import annotations

import asyncio
import os

from homeassistant.const import ATTR_ENTITY_ID, CONF_HOST, CONF_PORT, STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.marantz_avr.const import (
    CONF_CONNECTION_TYPE,
    CONF_SERIAL_URL,
    CONNECTION_NETWORK,
    CONNECTION_SERIAL,
    DOMAIN,
)

HOST = os.environ.get("MARANTZ_LIVE_HOST")
SERIAL_URL = os.environ.get("MARANTZ_LIVE_SERIAL_URL")
SNAPSHOT = os.environ.get("MARANTZ_LIVE_SNAPSHOT_CMD")  # optional, gets a label arg


async def _wait(hass: HomeAssistant, entity_id: str, predicate, timeout=10.0) -> None:
    async with asyncio.timeout(timeout):
        while True:
            state = hass.states.get(entity_id)
            if state is not None and predicate(state):
                return
            await asyncio.sleep(0.05)


async def _snapshot(label: str) -> None:
    if SNAPSHOT:
        proc = await asyncio.create_subprocess_shell(f"{SNAPSHOT} {label}")
        await proc.wait()


def _params():
    params = []
    if HOST:
        params.append(
            pytest.param(
                {
                    CONF_CONNECTION_TYPE: CONNECTION_NETWORK,
                    CONF_HOST: HOST,
                    CONF_PORT: 23,
                },
                id="network",
            )
        )
    if SERIAL_URL:
        params.append(
            pytest.param(
                {CONF_CONNECTION_TYPE: CONNECTION_SERIAL, CONF_SERIAL_URL: SERIAL_URL},
                id="serial",
            )
        )
    return params or [
        pytest.param(None, marks=pytest.mark.skip(reason="no live receiver"))
    ]


@pytest.fixture
def allow_network(monkeypatch: pytest.MonkeyPatch):
    """Lift pytest-socket's localhost-only restriction and use real timings."""
    import pytest_socket

    from custom_components.marantz_avr import protocol

    pytest_socket._remove_restrictions()
    # Undo the fast timings from conftest: real receivers drop commands sent
    # closer than 50 ms apart.
    monkeypatch.setattr(protocol, "COMMAND_INTERVAL", 0.06)
    monkeypatch.setattr(protocol, "POWER_ON_DELAY", 1.0)


@pytest.mark.parametrize("data", _params())
async def test_live(hass: HomeAssistant, allow_network, data) -> None:
    entry = MockConfigEntry(domain=DOMAIN, title="Live AVR", data=data)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    registry = er.async_get(hass)
    entities = sorted(
        e.entity_id for e in er.async_entries_for_config_entry(registry, entry.entry_id)
    )
    print(f"\n[{data[CONF_CONNECTION_TYPE]}] {len(entities)} entities:")
    for entity_id in entities:
        state = hass.states.get(entity_id)
        print(f"  {entity_id} = {state.state if state else None}")

    main = "media_player.live_avr"
    state = hass.states.get(main)
    print("  main attributes:", dict(state.attributes))
    assert state.state == STATE_ON, "main zone must be on for the live test"
    original_volume = state.attributes["volume_display"]
    original_dim = hass.states.get("select.live_avr_display_dimmer").state
    original_mode = state.attributes["sound_mode"]
    original_source = state.attributes["source"]

    try:
        # Volume in 0.5 dB steps
        target = original_volume - 1.5
        await hass.services.async_call(
            "media_player",
            "volume_set",
            {ATTR_ENTITY_ID: main, "volume_level": target / 98},
            blocking=True,
        )
        await _wait(hass, main, lambda s: s.attributes["volume_display"] == target)
        await _snapshot(f"{data[CONF_CONNECTION_TYPE]}_volume_{target}")
        await hass.services.async_call(
            "media_player", "volume_up", {ATTR_ENTITY_ID: main}, blocking=True
        )
        await _wait(hass, main, lambda s: s.attributes["volume_display"] > target)

        # Mute
        await hass.services.async_call(
            "media_player",
            "volume_mute",
            {ATTR_ENTITY_ID: main, "is_volume_muted": True},
            blocking=True,
        )
        await _wait(hass, main, lambda s: s.attributes["is_volume_muted"] is True)
        await _snapshot(f"{data[CONF_CONNECTION_TYPE]}_muted")
        await hass.services.async_call(
            "media_player",
            "volume_mute",
            {ATTR_ENTITY_ID: main, "is_volume_muted": False},
            blocking=True,
        )
        await _wait(hass, main, lambda s: s.attributes["is_volume_muted"] is False)

        # Display dimmer
        await hass.services.async_call(
            "select",
            "select_option",
            {ATTR_ENTITY_ID: "select.live_avr_display_dimmer", "option": "Dim"},
            blocking=True,
        )
        await _wait(hass, "select.live_avr_display_dimmer", lambda s: s.state == "Dim")
        await asyncio.sleep(1)
        await _snapshot(f"{data[CONF_CONNECTION_TYPE]}_dimmer_dim")

        # Sound mode
        await hass.services.async_call(
            "media_player",
            "select_sound_mode",
            {ATTR_ENTITY_ID: main, "sound_mode": "STEREO"},
            blocking=True,
        )
        await _wait(hass, main, lambda s: s.attributes["sound_mode"] == "STEREO")
        await asyncio.sleep(1)
        await _snapshot(f"{data[CONF_CONNECTION_TYPE]}_stereo")

        # Source
        await hass.services.async_call(
            "media_player",
            "select_source",
            {ATTR_ENTITY_ID: main, "source": "TV Audio"},
            blocking=True,
        )
        await _wait(hass, main, lambda s: s.attributes["source"] == "TV Audio")
        await asyncio.sleep(1)
        await _snapshot(f"{data[CONF_CONNECTION_TYPE]}_source_tv")

        # Bass via tone control
        tone = "switch.live_avr_tone_control"
        bass = "number.live_avr_bass"
        if hass.states.get(tone) and hass.states.get(bass):
            tone_was = hass.states.get(tone).state
            await hass.services.async_call(
                "switch", "turn_on", {ATTR_ENTITY_ID: tone}, blocking=True
            )
            await _wait(hass, tone, lambda s: s.state == "on")
            await hass.services.async_call(
                "number", "set_value", {ATTR_ENTITY_ID: bass, "value": 2}, blocking=True
            )
            await _wait(hass, bass, lambda s: s.state == "2")
            await hass.services.async_call(
                "number", "set_value", {ATTR_ENTITY_ID: bass, "value": 0}, blocking=True
            )
            await _wait(hass, bass, lambda s: s.state == "0")
            await hass.services.async_call(
                "switch", f"turn_{tone_was}", {ATTR_ENTITY_ID: tone}, blocking=True
            )
            await _wait(hass, tone, lambda s: s.state == tone_was)

        # Remote: open and close the setup menu
        await hass.services.async_call(
            "remote",
            "send_command",
            {ATTR_ENTITY_ID: "remote.live_avr", "command": ["menu_on"]},
            blocking=True,
        )
        await asyncio.sleep(1.5)
        await _snapshot(f"{data[CONF_CONNECTION_TYPE]}_menu")
        await hass.services.async_call(
            "remote",
            "send_command",
            {ATTR_ENTITY_ID: "remote.live_avr", "command": ["menu_off"]},
            blocking=True,
        )
    finally:
        await hass.services.async_call(
            "media_player",
            "select_source",
            {ATTR_ENTITY_ID: main, "source": original_source},
            blocking=True,
        )
        await _wait(hass, main, lambda s: s.attributes["source"] == original_source)
        await hass.services.async_call(
            "media_player",
            "select_sound_mode",
            {ATTR_ENTITY_ID: main, "sound_mode": original_mode},
            blocking=True,
        )
        await hass.services.async_call(
            "select",
            "select_option",
            {ATTR_ENTITY_ID: "select.live_avr_display_dimmer", "option": original_dim},
            blocking=True,
        )
        await hass.services.async_call(
            "media_player",
            "volume_set",
            {ATTR_ENTITY_ID: main, "volume_level": original_volume / 98},
            blocking=True,
        )
        await _wait(
            hass, main, lambda s: s.attributes["volume_display"] == original_volume
        )
        await asyncio.sleep(2)
        state = hass.states.get(main)
        print(
            "  restored:",
            state.attributes["source"],
            state.attributes["sound_mode"],
            state.attributes["volume_display"],
        )
        await _snapshot(f"{data[CONF_CONNECTION_TYPE]}_restored")
        assert await hass.config_entries.async_unload(entry.entry_id)
