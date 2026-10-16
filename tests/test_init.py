"""Integration tests against the fake receiver."""

from __future__ import annotations

import asyncio

from homeassistant.components.media_player import (
    ATTR_INPUT_SOURCE,
    ATTR_INPUT_SOURCE_LIST,
    ATTR_MEDIA_VOLUME_LEVEL,
    ATTR_MEDIA_VOLUME_MUTED,
    ATTR_SOUND_MODE,
)
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import (
    ATTR_ENTITY_ID,
    CONF_HOST,
    CONF_PORT,
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr, entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.marantz_avr.const import (
    CONF_CONNECTION_TYPE,
    CONF_SERIAL_URL,
    CONF_SOURCES,
    CONNECTION_NETWORK,
    CONNECTION_SERIAL,
    DOMAIN,
)

from .fake_receiver import FakeReceiver

MAIN = "media_player.marantz_cinema_40"
ZONE2 = "media_player.marantz_cinema_40_zone_2"


async def _wait_for(predicate, timeout: float = 5.0) -> None:
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.02)


async def _setup(
    hass: HomeAssistant, receiver: FakeReceiver, serial: bool = False, options=None
) -> MockConfigEntry:
    if serial:
        data = {
            CONF_CONNECTION_TYPE: CONNECTION_SERIAL,
            CONF_SERIAL_URL: f"socket://127.0.0.1:{receiver.port}",
        }
    else:
        data = {
            CONF_CONNECTION_TYPE: CONNECTION_NETWORK,
            CONF_HOST: "127.0.0.1",
            CONF_PORT: receiver.port,
        }
    entry = MockConfigEntry(
        domain=DOMAIN, title="Marantz CINEMA 40", data=data, options=options or {}
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _wait_state(hass: HomeAssistant, entity_id: str, predicate) -> None:
    await _wait_for(
        lambda: (s := hass.states.get(entity_id)) is not None and predicate(s)
    )


@pytest.mark.parametrize("serial", [False, True])
async def test_setup_creates_entities(
    hass: HomeAssistant, receiver: FakeReceiver, serial: bool
) -> None:
    entry = await _setup(hass, receiver, serial=serial)
    assert entry.state is ConfigEntryState.LOADED

    state = hass.states.get(MAIN)
    assert state.state == STATE_ON
    assert state.attributes[ATTR_MEDIA_VOLUME_LEVEL] == pytest.approx(46 / 98)
    assert state.attributes["volume_db"] == -34
    assert state.attributes[ATTR_INPUT_SOURCE] == "HEOS Music"
    assert state.attributes[ATTR_SOUND_MODE] == "MCH STEREO"
    assert state.attributes[ATTR_MEDIA_VOLUME_MUTED] is False
    # Names from SSFUN are used, AUX3-7 hidden by default.
    sources = state.attributes[ATTR_INPUT_SOURCE_LIST]
    assert "Blu-ray" in sources
    assert "TV Audio" in sources
    assert "AUX3" not in sources

    assert hass.states.get(ZONE2).state == STATE_OFF
    assert hass.states.get("select.marantz_cinema_40_dynamic_volume").state == "Off"
    assert hass.states.get("select.marantz_cinema_40_multeq").state == "Off"
    assert hass.states.get("switch.marantz_cinema_40_tone_control").state == STATE_OFF
    assert hass.states.get("switch.marantz_cinema_40_trigger_1").state == STATE_ON
    assert hass.states.get("number.marantz_cinema_40_bass").state == "0"
    assert hass.states.get("number.marantz_cinema_40_front_left_level").state == "0.0"
    assert hass.states.get("number.marantz_cinema_40_zone_2_bass").state == "0"
    assert (
        hass.states.get("sensor.marantz_cinema_40_video_output_resolution").state
        == "1080p60"
    )
    assert (
        hass.states.get("sensor.marantz_cinema_40_video_input_resolution").state
        == "No signal"
    )
    assert (
        hass.states.get("sensor.marantz_cinema_40_audio_sample_rate").state
        == "44.1 kHz"
    )
    assert hass.states.get("remote.marantz_cinema_40").state == STATE_ON
    # Not supported by the fake -> not created.
    assert hass.states.get("switch.marantz_cinema_40_trigger_3") is None
    assert hass.states.get("select.marantz_cinema_40_m_dax") is None

    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, entry.entry_id)})
    assert device.model == "CINEMA 40"
    assert device.sw_version == "5000-1063-7071-9831"

    assert await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_media_player_actions(
    hass: HomeAssistant, receiver: FakeReceiver
) -> None:
    await _setup(hass, receiver)

    await hass.services.async_call(
        "media_player",
        "volume_set",
        {ATTR_ENTITY_ID: MAIN, ATTR_MEDIA_VOLUME_LEVEL: 50.5 / 98},
        blocking=True,
    )
    await _wait_state(hass, MAIN, lambda s: s.attributes["volume_display"] == 50.5)
    assert "MV505" in receiver.received

    await hass.services.async_call(
        "media_player", "volume_up", {ATTR_ENTITY_ID: MAIN}, blocking=True
    )
    await _wait_state(hass, MAIN, lambda s: s.attributes["volume_display"] == 51)

    await hass.services.async_call(
        "media_player",
        "volume_mute",
        {ATTR_ENTITY_ID: MAIN, ATTR_MEDIA_VOLUME_MUTED: True},
        blocking=True,
    )
    await _wait_state(hass, MAIN, lambda s: s.attributes[ATTR_MEDIA_VOLUME_MUTED])

    await hass.services.async_call(
        "media_player",
        "select_source",
        {ATTR_ENTITY_ID: MAIN, ATTR_INPUT_SOURCE: "Blu-ray"},
        blocking=True,
    )
    await _wait_state(
        hass, MAIN, lambda s: s.attributes[ATTR_INPUT_SOURCE] == "Blu-ray"
    )
    assert "SIBD" in receiver.received

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            "media_player",
            "select_source",
            {ATTR_ENTITY_ID: MAIN, ATTR_INPUT_SOURCE: "Nope"},
            blocking=True,
        )

    await hass.services.async_call(
        "media_player",
        "select_sound_mode",
        {ATTR_ENTITY_ID: MAIN, ATTR_SOUND_MODE: "PURE DIRECT"},
        blocking=True,
    )
    await _wait_state(
        hass, MAIN, lambda s: s.attributes[ATTR_SOUND_MODE] == "PURE DIRECT"
    )

    await hass.services.async_call(
        "media_player", "turn_off", {ATTR_ENTITY_ID: MAIN}, blocking=True
    )
    await _wait_state(hass, MAIN, lambda s: s.state == STATE_OFF)
    assert "ZMOFF" in receiver.received

    # Zone 2
    await hass.services.async_call(
        "media_player", "turn_on", {ATTR_ENTITY_ID: ZONE2}, blocking=True
    )
    await _wait_state(hass, ZONE2, lambda s: s.state == STATE_ON)
    await hass.services.async_call(
        "media_player",
        "volume_set",
        {ATTR_ENTITY_ID: ZONE2, ATTR_MEDIA_VOLUME_LEVEL: 0.5},
        blocking=True,
    )
    await _wait_state(hass, ZONE2, lambda s: s.attributes["volume_display"] == 49)
    assert "Z249" in receiver.received
    await hass.services.async_call(
        "media_player",
        "select_source",
        {ATTR_ENTITY_ID: ZONE2, ATTR_INPUT_SOURCE: "TV Audio"},
        blocking=True,
    )
    await _wait_state(
        hass, ZONE2, lambda s: s.attributes[ATTR_INPUT_SOURCE] == "TV Audio"
    )
    assert "Z2TV" in receiver.received


async def test_setting_entities(hass: HomeAssistant, receiver: FakeReceiver) -> None:
    await _setup(hass, receiver)

    await hass.services.async_call(
        "select",
        "select_option",
        {ATTR_ENTITY_ID: "select.marantz_cinema_40_dynamic_volume", "option": "Medium"},
        blocking=True,
    )
    await _wait_state(
        hass, "select.marantz_cinema_40_dynamic_volume", lambda s: s.state == "Medium"
    )
    assert "PSDYNVOL MED" in receiver.received

    await hass.services.async_call(
        "select",
        "select_option",
        {ATTR_ENTITY_ID: "select.marantz_cinema_40_multeq", "option": "L/R Bypass"},
        blocking=True,
    )
    await _wait_state(
        hass, "select.marantz_cinema_40_multeq", lambda s: s.state == "L/R Bypass"
    )
    assert "PSMULTEQ:BYP.LR" in receiver.received

    await hass.services.async_call(
        "switch",
        "turn_on",
        {ATTR_ENTITY_ID: "switch.marantz_cinema_40_tone_control"},
        blocking=True,
    )
    await _wait_state(
        hass, "switch.marantz_cinema_40_tone_control", lambda s: s.state == STATE_ON
    )
    assert "PSTONE CTRL ON" in receiver.received

    await hass.services.async_call(
        "switch",
        "turn_on",
        {ATTR_ENTITY_ID: "switch.marantz_cinema_40_hdmi_upscaler"},
        blocking=True,
    )
    await _wait_state(
        hass, "switch.marantz_cinema_40_hdmi_upscaler", lambda s: s.state == STATE_ON
    )
    assert "VSSCHAUTO" in receiver.received

    for entity, value, command in (
        ("number.marantz_cinema_40_bass", -3, "PSBAS 47"),
        ("number.marantz_cinema_40_treble", 6, "PSTRE 56"),
        ("number.marantz_cinema_40_front_left_level", -1.5, "CVFL 485"),
        ("number.marantz_cinema_40_center_level", 2, "CVC 52"),
        ("number.marantz_cinema_40_lfe_level", -10, "PSLFE 10"),
        ("number.marantz_cinema_40_audio_delay", 120, "PSDELAY 120"),
        ("number.marantz_cinema_40_sleep_timer", 30, "SLP030"),
        ("number.marantz_cinema_40_sleep_timer", 0, "SLPOFF"),
        ("number.marantz_cinema_40_zone_2_bass", -10, "Z2PSBAS 40"),
    ):
        await hass.services.async_call(
            "number",
            "set_value",
            {ATTR_ENTITY_ID: entity, "value": value},
            blocking=True,
        )
        await _wait_for(lambda c=command: c in receiver.received)
        await _wait_state(hass, entity, lambda s, v=value: float(s.state) == v)

    await hass.services.async_call(
        "remote",
        "send_command",
        {ATTR_ENTITY_ID: "remote.marantz_cinema_40", "command": ["up", "PSDYNEQ ON"]},
        blocking=True,
    )
    await _wait_for(lambda: "PSDYNEQ ON" in receiver.received)
    assert "MNCUP" in receiver.received
    await _wait_state(
        hass, "switch.marantz_cinema_40_dynamic_eq", lambda s: s.state == STATE_ON
    )

    await hass.services.async_call(
        "remote",
        "turn_off",
        {ATTR_ENTITY_ID: "remote.marantz_cinema_40"},
        blocking=True,
    )
    await _wait_state(hass, "remote.marantz_cinema_40", lambda s: s.state == STATE_OFF)
    await _wait_state(hass, ZONE2, lambda s: s.state == STATE_OFF)


async def test_push_updates(hass: HomeAssistant, receiver: FakeReceiver) -> None:
    await _setup(hass, receiver)
    await receiver.push("MSDOLBY ATMOS")
    await receiver.push("PSDYNVOL HEV")
    await receiver.push("SITUNER")
    await receiver.push("TFAN010170")
    await _wait_state(
        hass, MAIN, lambda s: s.attributes.get("media_title") == "101.70 MHz"
    )
    assert hass.states.get(MAIN).attributes[ATTR_SOUND_MODE] == "DOLBY ATMOS"
    assert hass.states.get("select.marantz_cinema_40_dynamic_volume").state == "Heavy"
    assert (
        hass.states.get("sensor.marantz_cinema_40_tuner_frequency").state
        == "101.70 MHz"
    )


async def test_new_capability_added_at_runtime(
    hass: HomeAssistant, receiver: FakeReceiver
) -> None:
    await _setup(hass, receiver)
    assert hass.states.get("select.marantz_cinema_40_m_dax") is None
    await receiver.push("PSMDAX LOW")
    await _wait_for(
        lambda: hass.states.get("select.marantz_cinema_40_m_dax") is not None
    )
    assert hass.states.get("select.marantz_cinema_40_m_dax").state == "Low"


async def test_unavailable_and_recovers(
    hass: HomeAssistant, receiver: FakeReceiver
) -> None:
    entry = await _setup(hass, receiver)
    entry.runtime_data.client._reconnect_interval = 0.05
    await receiver.disconnect_all()
    await _wait_state(hass, MAIN, lambda s: s.state == STATE_UNAVAILABLE)
    await _wait_state(hass, MAIN, lambda s: s.state == STATE_ON)


async def test_capabilities_persist_when_offline(
    hass: HomeAssistant, receiver: FakeReceiver
) -> None:
    entry = await _setup(hass, receiver)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    # Receiver answers PW? but nothing else (e.g. busy); entities still exist.
    original = receiver.respond
    receiver.respond = lambda c: original(c) if c == "PW?" else []
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("select.marantz_cinema_40_dynamic_volume") is not None
    assert "Blu-ray" in hass.states.get(MAIN).attributes[ATTR_INPUT_SOURCE_LIST]
    receiver.respond = original
    await hass.config_entries.async_unload(entry.entry_id)


async def test_setup_retry_when_unreachable(
    hass: HomeAssistant, receiver: FakeReceiver
) -> None:
    receiver.mute_responses = True
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_CONNECTION_TYPE: CONNECTION_NETWORK,
            CONF_HOST: "127.0.0.1",
            CONF_PORT: receiver.port,
        },
    )
    entry.add_to_hass(hass)
    from unittest.mock import patch

    with patch(
        "custom_components.marantz_avr.protocol.MarantzClient.start",
        side_effect=__import__(
            "custom_components.marantz_avr.protocol", fromlist=["x"]
        ).MarantzConnectionError("nope"),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_source_options(hass: HomeAssistant, receiver: FakeReceiver) -> None:
    await _setup(hass, receiver, options={CONF_SOURCES: ["BD", "TV", "NET"]})
    assert hass.states.get(MAIN).attributes[ATTR_INPUT_SOURCE_LIST] == [
        "Blu-ray",
        "TV Audio",
        "HEOS Music",
    ]
    assert hass.states.get(ZONE2).attributes[ATTR_INPUT_SOURCE_LIST] == [
        "Main zone source",
        "Blu-ray",
        "TV Audio",
        "HEOS Music",
    ]


async def test_unique_ids_stable(hass: HomeAssistant, receiver: FakeReceiver) -> None:
    entry = await _setup(hass, receiver)
    registry = er.async_get(hass)
    ent = registry.async_get("switch.marantz_cinema_40_tone_control")
    assert ent.unique_id == f"{entry.entry_id}_pstone_ctrl"
