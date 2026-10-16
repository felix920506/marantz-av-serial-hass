"""Marantz AV receiver RS-232C / IP control protocol.

This module is deliberately free of Home Assistant imports so that it can be
tested (and reused) on its own.

The protocol is a simple line based ASCII protocol: every message is
``COMMAND + PARAMETER + CR``.  The receiver answers queries (``XX?``) and
also pushes unsolicited events whenever its state changes, so the client keeps
a long-lived connection open and maintains a key/value state cache.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable
import contextlib
from dataclasses import dataclass
import logging
import time
from urllib.parse import urlparse

_LOGGER = logging.getLogger(__name__)

CR = b"\r"
DEFAULT_PORT = 23
DEFAULT_BAUDRATE = 9600

# The spec requires at least 50 ms between commands and 1 s after power on.
COMMAND_INTERVAL = 0.06
POWER_ON_DELAY = 1.0
POWER_ON_COMMANDS = frozenset({"PWON", "ZMON", "Z2ON", "Z3ON"})

# Keys for which the receiver reports both an ON/OFF flag and a level using
# the same prefix (e.g. ``CVSW ON`` and ``CVSW 50``).  ON/OFF values are stored
# under ``<key>:ONOFF`` so they don't overwrite the level.
DUAL_VALUE_KEYS = frozenset({"PSSWL", "PSCLV", "CVTTR", "BTTX"})

# Response prefixes the parser knows.  Matched longest first.  The key used in
# the state cache is the prefix with trailing separators stripped.
KNOWN_PREFIXES: tuple[str, ...] = (
    # System
    "PW",
    "ZM",
    "MVMAX ",
    "MV",
    "MU",
    "SI",
    "SD",
    "SLP",
    "STBY",
    "ECO",
    "DIM ",
    "ILB ",
    "SPPR ",
    "BTTX ",
    "MSSMART",
    "MS",
    "SYMO",
    "SYSMI ",
    "SYSDA ",
    "NSFRN ",
    "SSINFAISFSV ",
    "SSINFAISSIG ",
    "SSINFFRMAVR ",
    "SSLAN ",
    "MNZST ",
    "MNMEN ",
    "SSHOSALS ",
    # Video
    "VSMONI",
    "VSAUDIO ",
    "VSSCH",
    "VSVPM",
    # Parameters
    "PSFRONT ",
    "PSSP:",
    "PSSWR ",
    "PSTONE CTRL ",
    "PSBAS ",
    "PSTRE ",
    "PSLOM ",
    "PSBSC ",
    "PSDEH ",
    "PSSWL2 ",
    "PSSWL3 ",
    "PSSWL4 ",
    "PSSWL ",
    "PSLFE ",
    "PSCES ",
    "PSSPV ",
    "PSDIC ",
    "PSNEURAL ",
    "PSIMAXAUD ",
    "PSIMAXHPF ",
    "PSIMAXLPF ",
    "PSIMAXSWO ",
    "PSIMAX ",
    "PSCINEMA EQ.",
    "PSMULTEQ:",
    "PSDYNEQ ",
    "PSREFLEV ",
    "PSSURLEV ",
    "PSDYNVOL ",
    "PSLFC ",
    "PSCNTAMT ",
    "PSGEQ ",
    "PSHEQ ",
    "PSDRC ",
    "PSMDAX ",
    "PSDELAY ",
    "PSAUROPR ",
    "PSAUROST ",
    "PSAUROMODE ",
    "PSDIRAC ",
    "PSDACFIL ",
    # Triggers
    "TR1 ",
    "TR2 ",
    "TR3 ",
    # Tuner
    "TFANNAME",
    "TFAN",
    "TPAN",
    # Zones (power / source / volume handled specially)
    "Z2MU",
    "Z2SMART",
    "Z2STBY",
    "Z2SLP",
    "Z2CS",
    "Z2HPF",
    "Z2PSBAS ",
    "Z2PSTRE ",
    "Z2HDA ",
    "Z3MU",
    "Z3SMART",
    "Z3STBY",
    "Z3SLP",
    "Z3CS",
    "Z3HPF",
    "Z3PSBAS ",
    "Z3PSTRE ",
)
_PREFIXES_SORTED = sorted(KNOWN_PREFIXES, key=len, reverse=True)

# Lines that are pure noise for us.
_IGNORED_PREFIXES = ("OPINF", "OPALS", "DC", "SSINFFRM ", "SSINFFRMDTS")


def key_for_prefix(prefix: str) -> str:
    """Return the state key for a response prefix."""
    return prefix.rstrip(" :.")


@dataclass(frozen=True, slots=True)
class Update:
    """A single parsed state update."""

    key: str
    value: str


def parse_line(line: str) -> list[Update]:
    """Parse a single line received from the receiver into state updates.

    Returns an empty list for lines that are not understood.  Some lines (like
    source names) produce keys that embed a sub-key, e.g. ``SSFUN:BD``.
    """
    line = line.rstrip("\r\n")
    if not line.strip():
        return []
    if line.startswith(_IGNORED_PREFIXES):
        return []

    # Channel volumes: CVFL 50 / CVSW ON / CVEND, also Z2CV / Z3CV.
    for cv_prefix in ("Z2CV", "Z3CV", "CV"):
        if line.startswith(cv_prefix):
            rest = line[len(cv_prefix) :]
            if rest == "END":
                return []
            channel, sep, value = rest.partition(" ")
            if not sep or not channel:
                return []
            key = f"{cv_prefix}{channel}"
            value = value.strip()
            if value in ("ON", "OFF"):
                return [Update(f"{key}:ONOFF", value)]
            return [Update(key, value)]

    # Source names / source usage (network only): SSFUNBD Blu-ray
    for ss_prefix in ("SSFUN", "SSSOD"):
        if line.startswith(ss_prefix):
            rest = line[len(ss_prefix) :]
            if rest.strip() == "END":
                return []
            code, _, value = rest.partition(" ")
            if not code:
                return []
            return [Update(f"{ss_prefix}:{code}", value.strip())]

    # Signal resolution: SSINFSIGRES I--- / SSINFSIGRES O1080p60
    if line.startswith("SSINFSIGRES "):
        rest = line[len("SSINFSIGRES ") :].strip()
        if rest[:1] in ("I", "O"):
            return [Update(f"SSINFSIGRES{rest[0]}", rest[1:])]
        return []

    # Tuner band / mode share the TMAN prefix.
    if line.startswith("TMAN"):
        value = line[4:].strip()
        if value in ("AUTO", "MANUAL"):
            return [Update("TMANMODE", value)]
        return [Update("TMAN", value)]

    # Zone 2/3 power, source and volume share a bare prefix.
    for zone in ("Z2", "Z3"):
        if line.startswith(zone) and not _starts_with_known(line):
            rest = line[2:].strip()
            if rest in ("ON", "OFF"):
                return [Update(f"{zone}PW", rest)]
            if rest.isdigit() or rest in ("UP", "DOWN"):
                return [Update(f"{zone}MV", rest)] if rest.isdigit() else []
            return [Update(f"{zone}SI", rest)]

    # Video select carries both a mode and a source.
    if line.startswith("SV"):
        rest = line[2:]
        if rest in ("ON", "OFF"):
            return [Update("SVMODE", rest)]
        return [Update("SV", rest)]

    prefix = _match_prefix(line)
    if prefix is None:
        return []
    key = key_for_prefix(prefix)
    value = line[len(prefix) :].strip()
    if key in DUAL_VALUE_KEYS and value in ("ON", "OFF"):
        return [Update(f"{key}:ONOFF", value)]
    return [Update(key, value)]


def _match_prefix(line: str) -> str | None:
    for prefix in _PREFIXES_SORTED:
        if line.startswith(prefix):
            return prefix
    return None


def _starts_with_known(line: str) -> bool:
    return _match_prefix(line) is not None


# ---------------------------------------------------------------------------
# Value codecs
# ---------------------------------------------------------------------------


def decode_half_step(raw: str) -> float | None:
    """Decode a ``50``/``505`` style value (3 chars = additional .5)."""
    raw = raw.strip()
    if not raw.isdigit():
        return None
    if len(raw) == 3:
        return int(raw[:2]) + 0.5
    return float(int(raw))


def encode_half_step(value: float) -> str:
    """Encode a value to the ``50``/``505`` style format."""
    doubled = round(value * 2)
    whole, half = divmod(doubled, 2)
    if half:
        return f"{whole:02d}5"
    return f"{whole:02d}"


def decode_volume(raw: str) -> float | None:
    """Decode master/zone volume into the absolute (0..98) scale."""
    return decode_half_step(raw)


def encode_volume(value: float, maximum: float = 98.0) -> str:
    """Encode an absolute volume (0..98) value."""
    value = min(max(value, 0.0), maximum)
    return encode_half_step(value)


# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------

type StreamPair = tuple[asyncio.StreamReader, asyncio.StreamWriter]
type Opener = Callable[[], Awaitable[StreamPair]]


def tcp_opener(host: str, port: int = DEFAULT_PORT, timeout: float = 10.0) -> Opener:
    """Return an opener for a plain TCP (telnet) connection."""

    async def _open() -> StreamPair:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout
        )
        _set_keepalive(writer)
        return reader, writer

    return _open


def serial_opener(url: str, baudrate: int = DEFAULT_BAUDRATE) -> Opener:
    """Return an opener for a serial port or a pyserial URL.

    ``socket://host:port`` URLs (raw TCP serial servers) are handled with a
    native asyncio socket; everything else (``/dev/ttyUSB0``,
    ``rfc2217://host:port`` ...) goes through pyserial.
    """
    if url.startswith("socket://"):
        parsed = urlparse(url)
        if not parsed.hostname or not parsed.port:
            raise ValueError(f"Invalid socket URL: {url}")
        return tcp_opener(parsed.hostname, parsed.port)

    async def _open() -> StreamPair:
        # Imported lazily so that network-only installs never need pyserial.
        import serial_asyncio_fast  # noqa: PLC0415

        return await asyncio.wait_for(
            serial_asyncio_fast.open_serial_connection(
                url=url, baudrate=baudrate, bytesize=8, parity="N", stopbits=1
            ),
            10,
        )

    return _open


def _set_keepalive(writer: asyncio.StreamWriter) -> None:
    sock = writer.get_extra_info("socket")
    if sock is None:
        return
    import socket  # noqa: PLC0415

    with contextlib.suppress(OSError, AttributeError):
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

type UpdateCallback = Callable[[list[Update]], None]
type ConnectionCallback = Callable[[bool], None]


class MarantzError(Exception):
    """Base error."""


class MarantzConnectionError(MarantzError):
    """Raised when the receiver can't be reached."""


class MarantzClient:
    """Persistent connection to a Marantz receiver with a state cache."""

    def __init__(
        self,
        opener: Opener,
        *,
        heartbeat_interval: float = 30.0,
        response_timeout: float = 5.0,
        reconnect_interval: float = 5.0,
        max_reconnect_interval: float = 60.0,
    ) -> None:
        """Initialize the client."""
        self._opener = opener
        self._heartbeat_interval = heartbeat_interval
        self._response_timeout = response_timeout
        self._reconnect_interval = reconnect_interval
        self._max_reconnect_interval = max_reconnect_interval

        self.state: dict[str, str] = {}
        self._update_callbacks: list[UpdateCallback] = []
        self._connection_callbacks: list[ConnectionCallback] = []
        self._connect_callbacks: list[Callable[[], Awaitable[None]]] = []

        self._writer: asyncio.StreamWriter | None = None
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._waiters: list[tuple[str, asyncio.Future[str]]] = []
        self._run_task: asyncio.Task[None] | None = None
        self._connected = False
        self._connected_event = asyncio.Event()
        self._closing = False
        self._last_rx = 0.0

    # -- public API ---------------------------------------------------------

    @property
    def connected(self) -> bool:
        """Return True while connected and the receiver is responding."""
        return self._connected

    def add_update_callback(self, callback: UpdateCallback) -> Callable[[], None]:
        """Register a callback for state updates; returns an unsubscribe."""
        self._update_callbacks.append(callback)
        return lambda: self._update_callbacks.remove(callback)

    def add_connection_callback(
        self, callback: ConnectionCallback
    ) -> Callable[[], None]:
        """Register a callback for connection state changes."""
        self._connection_callbacks.append(callback)
        return lambda: self._connection_callbacks.remove(callback)

    def add_connect_handler(
        self, handler: Callable[[], Awaitable[None]]
    ) -> Callable[[], None]:
        """Register a coroutine run after every (re)connect."""
        self._connect_callbacks.append(handler)
        return lambda: self._connect_callbacks.remove(handler)

    async def start(self, timeout: float = 15.0) -> None:
        """Start the connection loop and wait for the first connection."""
        self._closing = False
        self._run_task = asyncio.create_task(self._run(), name="marantz_client")
        try:
            await asyncio.wait_for(self._connected_event.wait(), timeout)
        except TimeoutError as err:
            await self.stop()
            raise MarantzConnectionError("Timed out connecting to receiver") from err

    async def stop(self) -> None:
        """Close the connection and stop reconnecting."""
        self._closing = True
        if self._run_task is not None:
            self._run_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._run_task
            self._run_task = None
        self._close_writer()

    async def send(self, *commands: str) -> None:
        """Queue one or more commands for sending."""
        for command in commands:
            self._queue.put_nowait(command)

    async def request(
        self, command: str, response_prefix: str, timeout: float | None = None
    ) -> str:
        """Send a command and wait for the first line starting with a prefix.

        Returns the full raw line.
        """
        loop = asyncio.get_running_loop()
        future: asyncio.Future[str] = loop.create_future()
        waiter = (response_prefix, future)
        self._waiters.append(waiter)
        try:
            await self.send(command)
            return await asyncio.wait_for(
                future, timeout if timeout is not None else self._response_timeout
            )
        finally:
            if waiter in self._waiters:
                self._waiters.remove(waiter)

    async def drain(self) -> None:
        """Wait until every queued command has been sent.

        Responses arrive within 200 ms of a request, so callers should allow
        a short grace period after this returns.
        """
        await self._queue.join()

    async def query(self, commands: Iterable[str]) -> None:
        """Queue several status requests."""
        await self.send(*commands)

    # -- internals ----------------------------------------------------------

    def _set_connected(self, connected: bool) -> None:
        if connected == self._connected:
            return
        self._connected = connected
        if connected:
            self._connected_event.set()
        else:
            self._connected_event.clear()
        for callback in list(self._connection_callbacks):
            try:
                callback(connected)
            except Exception:
                _LOGGER.exception("Error in connection callback")

    async def _run(self) -> None:
        delay = self._reconnect_interval
        while not self._closing:
            try:
                reader, writer = await self._opener()
            except (OSError, TimeoutError, ValueError) as err:
                _LOGGER.debug("Connection failed: %s; retrying in %ss", err, delay)
                await asyncio.sleep(delay)
                delay = min(delay * 2, self._max_reconnect_interval)
                continue
            except Exception:
                _LOGGER.exception("Unexpected error opening connection")
                await asyncio.sleep(delay)
                delay = min(delay * 2, self._max_reconnect_interval)
                continue

            self._writer = writer
            self._last_rx = time.monotonic()
            _LOGGER.debug("Connected")
            tasks = [
                asyncio.create_task(self._read_loop(reader)),
                asyncio.create_task(self._write_loop(writer)),
                asyncio.create_task(self._heartbeat_loop()),
            ]
            try:
                # Verify that the receiver is actually talking to us before
                # declaring the connection healthy (a serial server accepts the
                # TCP connection even if nothing is plugged in).
                try:
                    await self.request("PW?", "PW", self._response_timeout)
                except TimeoutError:
                    _LOGGER.debug("No response from receiver after connecting")
                else:
                    delay = self._reconnect_interval
                    self._set_connected(True)
                    for handler in list(self._connect_callbacks):
                        try:
                            await handler()
                        except Exception:
                            _LOGGER.exception("Error in connect handler")
                    await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            finally:
                for task in tasks:
                    task.cancel()
                for task in tasks:
                    with contextlib.suppress(asyncio.CancelledError, Exception):
                        await task
                self._close_writer()
                self._set_connected(False)
                self._fail_waiters()
                # Don't replay stale commands after a reconnect.
                while not self._queue.empty():
                    self._queue.get_nowait()
                    self._queue.task_done()
            if not self._closing:
                _LOGGER.debug("Disconnected; reconnecting in %ss", delay)
                await asyncio.sleep(delay)
                delay = min(delay * 2, self._max_reconnect_interval)

    def _close_writer(self) -> None:
        if self._writer is not None:
            with contextlib.suppress(Exception):
                self._writer.close()
            self._writer = None

    def _fail_waiters(self) -> None:
        for _, future in self._waiters:
            if not future.done():
                future.set_exception(MarantzConnectionError("Disconnected"))
        self._waiters.clear()

    async def _read_loop(self, reader: asyncio.StreamReader) -> None:
        buffer = b""
        while True:
            data = await reader.read(1024)
            if not data:
                _LOGGER.debug("Connection closed by peer")
                return
            self._last_rx = time.monotonic()
            buffer += data
            while CR in buffer:
                raw, buffer = buffer.split(CR, 1)
                line = raw.decode("ascii", errors="replace").strip("\n\x00")
                if line:
                    self._handle_line(line)
            if len(buffer) > 4096:
                buffer = b""

    def _handle_line(self, line: str) -> None:
        _LOGGER.debug("RX %s", line)
        for prefix, future in list(self._waiters):
            if line.startswith(prefix) and not future.done():
                future.set_result(line)
        updates = parse_line(line)
        if not updates:
            return
        changed = []
        for update in updates:
            if self.state.get(update.key) != update.value:
                self.state[update.key] = update.value
                changed.append(update)
        if not changed:
            return
        for callback in list(self._update_callbacks):
            try:
                callback(changed)
            except Exception:
                _LOGGER.exception("Error in update callback")

    async def _write_loop(self, writer: asyncio.StreamWriter) -> None:
        while True:
            command = await self._queue.get()
            try:
                _LOGGER.debug("TX %s", command)
                writer.write(command.encode("ascii", errors="replace") + CR)
                await writer.drain()
                await asyncio.sleep(
                    POWER_ON_DELAY if command in POWER_ON_COMMANDS else COMMAND_INTERVAL
                )
            finally:
                self._queue.task_done()

    async def _heartbeat_loop(self) -> None:
        while True:
            await asyncio.sleep(self._heartbeat_interval)
            if time.monotonic() - self._last_rx < self._heartbeat_interval:
                continue
            try:
                await self.request("PW?", "PW", self._response_timeout)
            except TimeoutError:
                _LOGGER.warning("Receiver stopped responding; reconnecting")
                return
