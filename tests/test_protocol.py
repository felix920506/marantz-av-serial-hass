"""Tests for the protocol module (no Home Assistant involved)."""

from __future__ import annotations

import asyncio

import pytest

from custom_components.marantz_avr.protocol import (
    MarantzClient,
    MarantzConnectionError,
    Update,
    decode_half_step,
    encode_half_step,
    parse_line,
    serial_opener,
    tcp_opener,
)

from .fake_receiver import FakeReceiver


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("PWON", [Update("PW", "ON")]),
        ("MV455", [Update("MV", "455")]),
        ("MVMAX 98", [Update("MVMAX", "98")]),
        ("SISAT/CBL", [Update("SI", "SAT/CBL")]),
        ("MSDOLBY AUDIO-DD+ +DSUR", [Update("MS", "DOLBY AUDIO-DD+ +DSUR")]),
        ("MSSMART2", [Update("MSSMART", "2")]),
        ("PSMULTEQ:BYP.LR", [Update("PSMULTEQ", "BYP.LR")]),
        ("PSCINEMA EQ.ON", [Update("PSCINEMA EQ", "ON")]),
        ("PSTONE CTRL ON", [Update("PSTONE CTRL", "ON")]),
        ("PSSWL ON", [Update("PSSWL:ONOFF", "ON")]),
        ("PSSWL 445", [Update("PSSWL", "445")]),
        ("PSSWL2 50", [Update("PSSWL2", "50")]),
        ("CVFL 505", [Update("CVFL", "505")]),
        ("CVSW ON", [Update("CVSW:ONOFF", "ON")]),
        ("CVEND", []),
        ("BTTX OFF", [Update("BTTX:ONOFF", "OFF")]),
        ("BTTX SP", [Update("BTTX", "SP")]),
        ("Z2ON", [Update("Z2PW", "ON")]),
        ("Z2SOURCE", [Update("Z2SI", "SOURCE")]),
        ("Z2CD", [Update("Z2SI", "CD")]),
        ("Z2CSMONO", [Update("Z2CS", "MONO")]),
        ("Z255", [Update("Z2MV", "55")]),
        ("Z2MUON", [Update("Z2MU", "ON")]),
        ("Z2CVFR 47", [Update("Z2CVFR", "47")]),
        ("Z3PSTRE 52", [Update("Z3PSTRE", "52")]),
        ("SSFUNSAT/CBL CBL/SAT    ", [Update("SSFUN:SAT/CBL", "CBL/SAT")]),
        ("SSSODTUNER DEL", [Update("SSSOD:TUNER", "DEL")]),
        ("SSFUN END", []),
        ("SSINFSIGRES I--- ", [Update("SSINFSIGRESI", "---")]),
        ("SSINFSIGRES O2160p60", [Update("SSINFSIGRESO", "2160p60")]),
        ("TMANFM", [Update("TMAN", "FM")]),
        ("TMANAUTO", [Update("TMANMODE", "AUTO")]),
        ("SVOFF", [Update("SVMODE", "OFF")]),
        ("SVAUX2", [Update("SV", "AUX2")]),
        ("TR3 OFF", [Update("TR3", "OFF")]),
        ("OPINFINS 1111", []),
        ("garbage", []),
        ("", []),
    ],
)
def test_parse_line(line: str, expected: list[Update]) -> None:
    assert parse_line(line) == expected


@pytest.mark.parametrize(
    ("raw", "value"),
    [("50", 50.0), ("505", 50.5), ("00", 0.0), ("98", 98.0), ("x", None)],
)
def test_half_step_codec(raw: str, value: float | None) -> None:
    assert decode_half_step(raw) == value
    if value is not None:
        assert encode_half_step(value) == raw


def test_encode_half_step_rounding() -> None:
    assert encode_half_step(45.24) == "45"
    assert encode_half_step(45.26) == "455"
    assert encode_half_step(5) == "05"


def test_serial_opener_invalid_socket_url() -> None:
    with pytest.raises(ValueError):
        serial_opener("socket://nohost")


async def _wait_for(predicate, timeout: float = 5.0) -> None:
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.02)


async def test_client_state_and_events(receiver: FakeReceiver) -> None:
    client = MarantzClient(tcp_opener("127.0.0.1", receiver.port))
    updates: list[Update] = []
    client.add_update_callback(updates.extend)
    await client.start()
    try:
        assert client.connected
        assert client.state["PW"] == "ON"
        await client.query(["MV?", "SI?"])
        await _wait_for(lambda: "SI" in client.state)
        assert client.state["MV"] == "46"
        assert client.state["SI"] == "NET"

        # Unsolicited event
        await receiver.push("MV50")
        await _wait_for(lambda: client.state["MV"] == "50")
        assert Update("MV", "50") in updates

        # Command round trip
        line = await client.request("MUON", "MU")
        assert line == "MUON"
        assert client.state["MU"] == "ON"
    finally:
        await client.stop()
    assert not client.connected


async def test_client_reconnects(receiver: FakeReceiver) -> None:
    client = MarantzClient(
        tcp_opener("127.0.0.1", receiver.port), reconnect_interval=0.05
    )
    states: list[bool] = []
    client.add_connection_callback(states.append)
    await client.start()
    try:
        await receiver.disconnect_all()
        await _wait_for(lambda: states[-1] is False)
        await _wait_for(lambda: client.connected)
        assert states == [True, False, True]
    finally:
        await client.stop()


async def test_client_heartbeat_detects_silence(receiver: FakeReceiver) -> None:
    client = MarantzClient(
        tcp_opener("127.0.0.1", receiver.port),
        heartbeat_interval=0.1,
        response_timeout=0.2,
        reconnect_interval=0.05,
    )
    await client.start()
    try:
        receiver.mute_responses = True
        await _wait_for(lambda: not client.connected)
        receiver.mute_responses = False
        await _wait_for(lambda: client.connected)
    finally:
        await client.stop()


async def test_client_no_response(receiver: FakeReceiver) -> None:
    receiver.mute_responses = True
    client = MarantzClient(tcp_opener("127.0.0.1", receiver.port), response_timeout=0.2)
    with pytest.raises(MarantzConnectionError):
        await client.start(timeout=0.5)
    assert not client.connected


async def test_client_respects_command_spacing(
    receiver: FakeReceiver, monkeypatch: pytest.MonkeyPatch
) -> None:
    from custom_components.marantz_avr import protocol

    monkeypatch.setattr(protocol, "COMMAND_INTERVAL", 0.06)
    client = MarantzClient(tcp_opener("127.0.0.1", receiver.port))
    await client.start()
    try:
        loop = asyncio.get_running_loop()
        start = loop.time()
        await client.send("PSBAS 51", "PSBAS 52", "PSBAS 53")
        await _wait_for(lambda: client.state.get("PSBAS") == "53")
        assert loop.time() - start >= 0.1
        assert receiver.received[-3:] == ["PSBAS 51", "PSBAS 52", "PSBAS 53"]
    finally:
        await client.stop()
