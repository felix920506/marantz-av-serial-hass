"""A small fake Marantz receiver speaking the RS-232C/IP protocol over TCP.

It is seeded with responses captured from a real CINEMA 40.
"""

from __future__ import annotations

import asyncio
import contextlib

# Initial state: response line per "slot".  Slots are named after the prefix
# whose value they hold.
INITIAL: dict[str, str] = {
    "PW": "PWON",
    "ZM": "ZMON",
    "MV": "MV46",
    "MVMAX": "MVMAX 98",
    "MU": "MUOFF",
    "SI": "SINET",
    "MS": "MSMCH STEREO",
    "SD": "SDAUTO",
    "SLP": "SLPOFF",
    "STBY": "STBYOFF",
    "ECO": "ECOAUTO",
    "DIM": "DIM BRI",
    "ILB": "ILB AUTO",
    "SPPR": "SPPR 1",
    "SYSMI": "SYSMI Multi Ch Stereo",
    "SYSDA": "SYSDA PCM                  ",
    "PSTONE CTRL": "PSTONE CTRL OFF",
    "PSBAS": "PSBAS 50",
    "PSTRE": "PSTRE 50",
    "PSDYNEQ": "PSDYNEQ OFF",
    "PSMULTEQ": "PSMULTEQ:OFF",
    "PSDYNVOL": "PSDYNVOL OFF",
    "PSREFLEV": "PSREFLEV 0",
    "PSLFE": "PSLFE 00",
    "PSDRC": "PSDRC OFF",
    "PSDELAY": "PSDELAY 000",
    "PSSWR": "PSSWR ON",
    "PSDIRAC": "PSDIRAC OFF",
    "PSSP": "PSSP:HF",
    "VSMONI": "VSMONIAUTO",
    "VSSCH": "VSSCHOFF",
    "TR1": "TR1 ON",
    "TR2": "TR2 ON",
    "CVFL": "CVFL 50",
    "CVFR": "CVFR 50",
    "CVC": "CVC 50",
    "CVSW": "CVSW 50",
    "Z2PW": "Z2OFF",
    "Z2SI": "Z2SOURCE",
    "Z2MV": "Z240",
    "Z2MU": "Z2MUOFF",
    "Z2PSBAS": "Z2PSBAS 50",
    "SSINFSIGRESI": "SSINFSIGRES I--- ",
    "SSINFSIGRESO": "SSINFSIGRES O1080p60",
    "SSINFAISFSV": "SSINFAISFSV 441",
}

# Query -> slots answered.
QUERIES: dict[str, list[str]] = {
    "PW?": ["PW"],
    "ZM?": ["ZM"],
    "MV?": ["MV", "MVMAX"],
    "MU?": ["MU"],
    "SI?": ["SI"],
    "MS?": ["MS", "SYSMI", "SYSDA"],
    "SD?": ["SD"],
    "SLP?": ["SLP"],
    "STBY?": ["STBY"],
    "ECO?": ["ECO"],
    "DIM ?": ["DIM"],
    "ILB ?": ["ILB"],
    "SPPR ?": ["SPPR"],
    "PSTONE CTRL ?": ["PSTONE CTRL"],
    "PSBAS ?": ["PSBAS"],
    "PSTRE ?": ["PSTRE"],
    "PSDYNEQ ?": ["PSDYNEQ"],
    "PSMULTEQ: ?": ["PSMULTEQ"],
    "PSDYNVOL ?": ["PSDYNVOL"],
    "PSREFLEV ?": ["PSREFLEV"],
    "PSLFE ?": ["PSLFE"],
    "PSDRC ?": ["PSDRC"],
    "PSDELAY ?": ["PSDELAY"],
    "PSSWR ?": ["PSSWR"],
    "PSDIRAC ?": ["PSDIRAC"],
    "PSSP: ?": ["PSSP"],
    "VSMONI ?": ["VSMONI"],
    "VSSCH ?": ["VSSCH"],
    "TR?": ["TR1", "TR2"],
    "CV?": ["CVFL", "CVFR", "CVC", "CVSW", "CVEND"],
    "Z2?": ["Z2PW", "Z2SI", "Z2MV"],
    "Z2MU?": ["Z2MU"],
    "Z2PSBAS ?": ["Z2PSBAS"],
    "SSINFSIGRES ?": ["SSINFSIGRESI", "SSINFSIGRESO"],
    "SSINFAISFSV ?": ["SSINFAISFSV"],
}

STATIC: dict[str, list[str]] = {
    "SYMO": ["SYMOCINEMA 40USA"],
    "NSFRN ?": ["NSFRN Marantz CINEMA 40"],
    "SSINFFRM ?": [
        "SSINFFRMAVR 5000-1063-7071-9831",
        "SSINFFRMDTS 4.30.10.15",
        "SSINFFRM END",
    ],
    "SSFUN ?": [
        "SSFUNBD Blu-ray         ",
        "SSFUNTV TV Audio        ",
        "SSFUNGAME1 Game1           ",
        "SSFUN END",
    ],
}

# Setter prefixes -> slot.  Value is the rest of the command.
SETTERS: list[tuple[str, str, str]] = [
    # (command prefix, slot, response prefix)
    ("PSTONE CTRL ", "PSTONE CTRL", "PSTONE CTRL "),
    ("PSBAS ", "PSBAS", "PSBAS "),
    ("PSTRE ", "PSTRE", "PSTRE "),
    ("PSDYNEQ ", "PSDYNEQ", "PSDYNEQ "),
    ("PSMULTEQ:", "PSMULTEQ", "PSMULTEQ:"),
    ("PSDYNVOL ", "PSDYNVOL", "PSDYNVOL "),
    ("PSREFLEV ", "PSREFLEV", "PSREFLEV "),
    ("PSLFE ", "PSLFE", "PSLFE "),
    ("PSDRC ", "PSDRC", "PSDRC "),
    ("PSDELAY ", "PSDELAY", "PSDELAY "),
    ("PSSWR ", "PSSWR", "PSSWR "),
    ("PSDIRAC ", "PSDIRAC", "PSDIRAC "),
    ("PSSP:", "PSSP", "PSSP:"),
    ("VSMONI", "VSMONI", "VSMONI"),
    ("VSSCH", "VSSCH", "VSSCH"),
    ("TR1 ", "TR1", "TR1 "),
    ("TR2 ", "TR2", "TR2 "),
    ("DIM ", "DIM", "DIM "),
    ("ILB ", "ILB", "ILB "),
    ("SPPR ", "SPPR", "SPPR "),
    ("ECO", "ECO", "ECO"),
    ("STBY", "STBY", "STBY"),
    ("SLP", "SLP", "SLP"),
    ("SD", "SD", "SD"),
    ("CVFL ", "CVFL", "CVFL "),
    ("CVFR ", "CVFR", "CVFR "),
    ("CVC ", "CVC", "CVC "),
    ("CVSW ", "CVSW", "CVSW "),
    ("Z2MU", "Z2MU", "Z2MU"),
    ("Z2PSBAS ", "Z2PSBAS", "Z2PSBAS "),
]


class FakeReceiver:
    """Fake receiver TCP server."""

    def __init__(self) -> None:
        self.state = dict(INITIAL)
        self.received: list[str] = []
        self.server: asyncio.Server | None = None
        self.writers: list[asyncio.StreamWriter] = []
        self.port = 0
        self.mute_responses = False

    async def start(self) -> None:
        self.server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        await self.disconnect_all()
        if self.server:
            self.server.close()
            await self.server.wait_closed()

    async def disconnect_all(self) -> None:
        for writer in self.writers:
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()
        self.writers.clear()

    async def push(self, line: str) -> None:
        """Send an unsolicited event to all clients."""
        for writer in self.writers:
            writer.write(line.encode() + b"\r")
            await writer.drain()

    async def _handle(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        self.writers.append(writer)
        buf = b""
        try:
            while True:
                data = await reader.read(1024)
                if not data:
                    break
                buf += data
                while b"\r" in buf:
                    raw, buf = buf.split(b"\r", 1)
                    command = raw.decode()
                    self.received.append(command)
                    if self.mute_responses:
                        continue
                    for line in self.respond(command):
                        writer.write(line.encode() + b"\r")
                    await writer.drain()
        except (ConnectionError, asyncio.CancelledError):
            pass
        finally:
            if writer in self.writers:
                self.writers.remove(writer)

    def _slots(self, *slots: str) -> list[str]:
        return [
            "CVEND" if s == "CVEND" else self.state[s]
            for s in slots
            if s == "CVEND" or s in self.state
        ]

    def respond(self, command: str) -> list[str]:
        if command in QUERIES:
            return self._slots(*QUERIES[command])
        if command in STATIC:
            return STATIC[command]
        if command == "PWON":
            self.state["PW"] = "PWON"
            self.state["ZM"] = "ZMON"
            return ["ZMON", "PWON"]
        if command == "PWSTANDBY":
            self.state["PW"] = "PWSTANDBY"
            self.state["ZM"] = "ZMOFF"
            self.state["Z2PW"] = "Z2OFF"
            return ["PWSTANDBY", "ZMOFF", "Z2OFF"]
        if command in ("ZMON", "ZMOFF"):
            self.state["ZM"] = command
            on = command == "ZMON" or self.state["Z2PW"] == "Z2ON"
            self.state["PW"] = "PWON" if on else "PWSTANDBY"
            return [command, self.state["PW"]]
        if command in ("MUON", "MUOFF"):
            self.state["MU"] = command
            return [command]
        if command.startswith("MV"):
            rest = command[2:]
            cur = self.state["MV"][2:]
            value = int(cur[:2]) + (0.5 if len(cur) == 3 else 0)
            if rest == "UP":
                value += 0.5
            elif rest == "DOWN":
                value -= 0.5
            else:
                value = int(rest[:2]) + (0.5 if len(rest) == 3 else 0)
            value = max(0, min(98, value))
            raw = f"{int(value):02d}" + ("5" if value % 1 else "")
            self.state["MV"] = f"MV{raw}"
            return [self.state["MV"], "MVMAX 98"]
        if command.startswith("SI"):
            self.state["SI"] = command
            return [command]
        if command.startswith("MS") and command not in ("MS?",):
            self.state["MS"] = command
            return [command]
        if command in ("Z2ON", "Z2OFF"):
            self.state["Z2PW"] = command
            return [command]
        if command.startswith("Z2") and command[2:].isdigit():
            self.state["Z2MV"] = command
            return [command]
        for prefix, slot, resp in SETTERS:
            if command.startswith(prefix):
                value = command[len(prefix) :]
                if "?" in value:
                    return self._slots(slot)
                self.state[slot] = f"{resp}{value}"
                return [self.state[slot]]
        if command.startswith("Z2") and command[2:] not in ("?",):
            self.state["Z2SI"] = command
            return [command]
        return []
