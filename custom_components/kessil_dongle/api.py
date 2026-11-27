"""Async client for the local TCP protocol of the Kessil WiFi dongle.

Deliberately free of Home Assistant imports so it can be tested on its own.
See docs/PROTOCOL.md for the wire format.
"""

from __future__ import annotations

import asyncio
import json
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any

DEFAULT_PORT = 8888
DEFAULT_TIMEOUT = 10.0
READ_CHUNK = 65536
MAX_RESPONSE = 1024 * 1024

# Group / lamp type -> key used in the program list (dtype 105/114)
TYPE_KEYS: dict[int, str] = {0: "Z2T", 1: "TB", 2: "TS", 3: "RF"}
TYPE_NAMES: dict[int, str] = {
    0: "0-10V",
    1: "Tuna Blue",
    2: "Tuna Sun",
    3: "Refugium",
}

# A group whose pid is one of these runs the manual setting, not a program.
MANUAL_PIDS = (0, -1)
MANUAL_PID = 0
UI_CHANNELS = 5
MINUTES_PER_DAY = 1440


class KessilError(Exception):
    """Base error."""


class KessilConnectionError(KessilError):
    """Dongle not reachable, timed out, or sent garbage."""


class KessilCommandError(KessilError):
    """Dongle answered with a non-zero code."""

    def __init__(self, dtype: int, code: Any, msg: Any) -> None:
        super().__init__(f"dtype {dtype}: {msg} (code {code})")
        self.dtype = dtype
        self.code = code
        self.msg = msg


@dataclass(frozen=True, slots=True)
class Lamp:
    kid: int
    gid: int
    model: str
    firmware: str
    type: int
    temp: int

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> Lamp:
        return cls(
            kid=int(raw["KID"]),
            gid=int(raw.get("GID", -1)),
            model=str(raw.get("model", "Kessil")),
            firmware=str(raw.get("FWVer", "")),
            type=int(raw.get("type", -1)),
            temp=int(raw.get("temp", 0)),
        )


@dataclass(frozen=True, slots=True)
class Group:
    gid: int
    pid: int
    type: int
    name: str
    lamp_count: int
    paused: bool
    ui: tuple[int, ...]

    @property
    def is_manual(self) -> bool:
        return self.pid in MANUAL_PIDS

    @property
    def type_key(self) -> str | None:
        return TYPE_KEYS.get(self.type)

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> Group:
        ui = [int(v) for v in raw.get("UI", [])][:UI_CHANNELS]
        ui += [0] * (UI_CHANNELS - len(ui))
        return cls(
            gid=int(raw["gid"]),
            pid=int(raw.get("pid", -1)),
            type=int(raw.get("type", -1)),
            name=str(raw.get("name", "")),
            lamp_count=int(raw.get("hasLamps", 0)),
            paused=bool(raw.get("pause", 0)),
            ui=tuple(ui),
        )


@dataclass(frozen=True, slots=True)
class ProgramPoint:
    minutes: int
    ui: tuple[int, ...]
    effect: int = -1  # eid; -1 = none, 0 = thunderstorm
    duration: int = 0  # effect duration in seconds


@dataclass(frozen=True, slots=True)
class Program:
    pid: int
    type: int
    name: str
    points: tuple[ProgramPoint, ...] = field(default_factory=tuple)

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> Program:
        points = []
        for p in raw.get("points", []):
            ui = [int(v) for v in p.get("UI", [])][:UI_CHANNELS]
            ui += [0] * (UI_CHANNELS - len(ui))
            points.append(
                ProgramPoint(
                    minutes=int(p["minutes"]),
                    ui=tuple(ui),
                    effect=int(p.get("eid", -1)),
                    duration=int(p.get("duration", 0)),
                )
            )
        points.sort(key=lambda p: p.minutes)
        return cls(
            pid=int(raw["PID"]),
            type=int(raw.get("type", -1)),
            name=str(raw.get("name", f"Program {raw['PID']}")),
            points=tuple(points),
        )

    def value_at(self, minute: float) -> tuple[int, ...] | None:
        """Channel values at `minute` after midnight (dongle clock).

        Linear fade between points, wrapping around midnight from the last
        point of the day to the first one.
        """
        pts = self.points
        if not pts:
            return None
        minute %= MINUTES_PER_DAY
        for idx, cur in enumerate(pts):
            nxt = pts[(idx + 1) % len(pts)]
            start, end, m = cur.minutes, nxt.minutes, minute
            if end <= start:  # segment crosses midnight (or single point)
                end += MINUTES_PER_DAY
                if m < start:
                    m += MINUTES_PER_DAY
            if start <= m < end:
                t = (m - start) / (end - start)
                return tuple(round(a + (b - a) * t) for a, b in zip(cur.ui, nxt.ui, strict=True))
        return pts[0].ui


@dataclass(frozen=True, slots=True)
class SystemInfo:
    serial: str
    firmware: str
    timezone: str
    group_ids: tuple[int, ...]
    program_ids: dict[str, tuple[int, ...]]
    lamps: tuple[Lamp, ...]

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> SystemInfo:
        return cls(
            serial=str(raw.get("sn", "")),
            firmware=str(raw.get("ver", "")),
            timezone=str(raw.get("timezone", "")),
            group_ids=tuple(int(g) for g in raw.get("group_ids", [])),
            program_ids=_parse_program_ids(raw.get("num_prog_ids", {})),
            lamps=tuple(Lamp.from_json(lamp) for lamp in raw.get("lamps", [])),
        )


def _parse_program_ids(raw: dict[str, Any]) -> dict[str, tuple[int, ...]]:
    result: dict[str, tuple[int, ...]] = {}
    for key, entries in raw.items():
        ordered = sorted(entries, key=lambda e: e.get("order", 0))
        result[key] = tuple(int(e["PID"]) for e in ordered)
    return result


def _try_decode(buf: bytes) -> dict[str, Any] | None:
    """Return the first complete JSON object in buf, or None if incomplete."""
    text = buf.decode("utf-8", errors="replace").strip()
    if not text:
        return None
    try:
        obj, _ = json.JSONDecoder().raw_decode(text)
    except ValueError:
        return None
    if not isinstance(obj, dict):
        raise KessilConnectionError(f"Unexpected response: {text[:200]}")
    return obj


class KessilDongle:
    """One TCP connection per command, commands serialized by a lock."""

    def __init__(
        self,
        host: str,
        port: int = DEFAULT_PORT,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self._lock = asyncio.Lock()

    async def request(self, dtype: int, data: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = json.dumps({"dtype": dtype, "data": data or {}}, separators=(",", ":")).encode()
        async with self._lock:
            try:
                async with asyncio.timeout(self.timeout):
                    response = await self._exchange(payload)
            except TimeoutError as err:
                raise KessilConnectionError(f"Timeout talking to {self.host}:{self.port}") from err
            except OSError as err:
                raise KessilConnectionError(f"Cannot reach {self.host}:{self.port}: {err}") from err
        if response.get("code") != 0:
            raise KessilCommandError(dtype, response.get("code"), response.get("msg"))
        return response

    async def _exchange(self, payload: bytes) -> dict[str, Any]:
        reader, writer = await asyncio.open_connection(self.host, self.port)
        try:
            writer.write(payload)
            await writer.drain()
            buf = b""
            while True:
                chunk = await reader.read(READ_CHUNK)
                if not chunk:
                    break
                buf += chunk
                if len(buf) > MAX_RESPONSE:
                    raise KessilConnectionError("Response too large")
                if (obj := _try_decode(buf)) is not None:
                    return obj
            if (obj := _try_decode(buf)) is not None:
                return obj
            raise KessilConnectionError(
                f"Incomplete response: {buf[:200].decode(errors='replace')!r}"
            )
        finally:
            writer.close()
            with suppress(OSError):
                await writer.wait_closed()

    # --- read-only ---------------------------------------------------------

    async def get_serial(self) -> str:
        """dtype 117 – cheap connectivity check, returns the dongle serial."""
        resp = await self.request(117)
        return str(resp["SN"])

    async def get_system_info(self) -> SystemInfo:
        return SystemInfo.from_json(await self.request(114))

    async def get_lamps(self) -> list[Lamp]:
        resp = await self.request(5)
        return [Lamp.from_json(lamp) for lamp in resp.get("lamps", [])]

    async def get_group(self, gid: int) -> Group:
        resp = await self.request(102, {"GID": gid})
        return Group.from_json(resp["group"])

    async def get_program_ids(self) -> dict[str, tuple[int, ...]]:
        resp = await self.request(105)
        return _parse_program_ids(resp.get("prog_ids", {}))

    async def get_program(self, pid: int, type_: int) -> Program:
        resp = await self.request(106, {"PID": pid, "type": type_})
        return Program.from_json(resp["program"])

    # --- write ---------------------------------------------------------------

    async def run_program(self, gid: int, pid: int) -> None:
        """dtype 100 – run a program; pid 0 switches the group to manual."""
        await self.request(100, {"GID": gid, "PID": pid})

    async def set_manual(
        self, gid: int, ui: tuple[int, ...] | list[int], *, save: bool = True
    ) -> None:
        """dtype 3 – set the manual channel values (0–255 each)."""
        if len(ui) != UI_CHANNELS:
            raise ValueError(f"need {UI_CHANNELS} channel values")
        data: dict[str, Any] = {"GID": gid}
        for idx, value in enumerate(ui, start=1):
            data[f"UI{idx}"] = max(0, min(255, int(value)))
        data["save"] = 1 if save else 0
        data["enabled"] = 1
        await self.request(3, data)
