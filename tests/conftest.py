"""Test helpers: load the HA-free protocol client and a fake dongle server."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures"

# Import api.py directly so the tests don't need Home Assistant installed.
_spec = importlib.util.spec_from_file_location(
    "kessil_api", ROOT / "custom_components" / "kessil_dongle" / "api.py"
)
api = importlib.util.module_from_spec(_spec)
sys.modules["kessil_api"] = api
_spec.loader.exec_module(api)


def fixture_text(name: str) -> str:
    return (FIXTURES / f"dtype_{name}.json").read_text()


DEFAULT_RESPONSES = {
    (117, None): fixture_text("117"),
    (114, None): fixture_text("114"),
    (5, None): fixture_text("5"),
    (102, 2): fixture_text("102_gid2"),
    (105, None): fixture_text("105"),
    (106, 1): fixture_text("106_pid1"),
    (106, 3): fixture_text("106_pid3"),
    (106, 0): fixture_text("106_pid0"),
    (100, None): '{"msg":"Success","code":0,"dType":100}',
    (3, None): '{"msg":"Success","code":0,"dType":3}',
}
INVALID = '{"msg":"Invalid command or parameters","code":-1,"dType":-1}'


class FakeDongle:
    """Answers like the real dongle: raw JSON in, (possibly chunked) JSON out."""

    def __init__(self) -> None:
        self.requests: list[dict] = []
        self.responses = dict(DEFAULT_RESPONSES)
        self.chunk_size: int | None = None
        self.delay = 0.0
        self.silent = False
        self.active = 0
        self.max_active = 0
        self.server: asyncio.Server | None = None
        self.port = 0

    def _lookup(self, req: dict) -> str:
        dtype = req["dtype"]
        data = req.get("data") or {}
        key = data.get("GID") if dtype == 102 else data.get("PID") if dtype == 106 else None
        return self.responses.get((dtype, key), INVALID)

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            raw = await reader.read(65536)
            req = json.loads(raw)
            self.requests.append(req)
            if self.silent:
                await asyncio.sleep(1)
                return
            body = self._lookup(req).encode()
            await asyncio.sleep(self.delay)
            step = self.chunk_size or len(body)
            for i in range(0, len(body), step):
                writer.write(body[i : i + step])
                await writer.drain()
                if self.chunk_size:
                    await asyncio.sleep(0.01)
        finally:
            self.active -= 1
            writer.close()

    async def __aenter__(self) -> FakeDongle:
        self.server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]
        return self

    async def __aexit__(self, *exc) -> None:
        self.server.close()
        await self.server.wait_closed()


@pytest.fixture
def fake() -> FakeDongle:
    return FakeDongle()


try:
    import pytest_socket  # noqa: F401  (present when the HA test framework is installed)
except ImportError:
    pass
else:

    @pytest.fixture(autouse=True)
    def _allow_localhost_sockets(socket_enabled):
        """The fake dongle is a real TCP server on 127.0.0.1."""
        yield
