"""WebSocket client and polling loop for an AMiT station (JSON protocol)."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .const import SIGNAL

_LOGGER = logging.getLogger(__name__)
TIMEOUT = 2
SCALAR_TYPES = {"BOOL", "BYTE", "CHAR", "WORD", "DWORD", "DINT", "REAL", "INT", "STRING"}


class AmitError(Exception):
    """Communication error with the station."""


class AmitClient:
    """One persistent WebSocket connection, JSON frames, request/response."""

    def __init__(self, session, url, user, password):
        self._session = session
        self._url = url
        self._user = user
        self._md5 = hashlib.md5(password.encode()).hexdigest() if user else ""
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._lock = asyncio.Lock()

    async def close(self) -> None:
        if self._ws is not None and not self._ws.closed:
            await self._ws.close()
        self._ws = None

    async def _request(self, command: str, **extra) -> dict:
        msg = {"command": command, **extra}
        if self._user:
            msg = {"user": self._user, "password": self._md5, **msg}
        async with self._lock:
            try:
                async with asyncio.timeout(TIMEOUT):
                    if self._ws is None or self._ws.closed:
                        self._ws = await self._session.ws_connect(self._url)
                    await self._ws.send_str(json.dumps(msg))
                    reply = await self._ws.receive()
                if reply.type is aiohttp.WSMsgType.TEXT:
                    return json.loads(reply.data)
                raise AmitError(f"unexpected frame: {reply.type.name}")
            except (aiohttp.ClientError, OSError, TimeoutError, ValueError, AmitError) as exc:
                await self.close()
                raise AmitError(str(exc) or type(exc).__name__) from exc

    async def read(self, names: list[str]) -> dict:
        resp = await self._request("read-req", items=[{"name": n} for n in names])
        result = {}
        for item in resp.get("items", []):
            if item.get("status", 1) == 0:
                result[item["name"]] = item.get("value")
        return result

    async def write(self, name: str, value) -> None:
        resp = await self._request("write-req", items=[{"name": name, "value": value}])
        item = (resp.get("items") or [{}])[0]
        if item.get("status", 1) != 0:
            raise AmitError(f"{name}: {item.get('text', item.get('status'))}")
    async def dump(self) -> dict[str, str]:
        """All scalar variables of the station: {name: type}."""
        found: dict[str, str] = {}
        start = 0
        while start < 1000:
            resp = await self._request("datadump-req", **{"from": start, "count": 100})
            chunk = resp.get("items", [])
            for item in chunk:
                vtype = str(item.get("type", ""))
                if item.get("name") and vtype in SCALAR_TYPES:
                    found[item["name"]] = vtype
            if len(chunk) < 100:
                break
            start += 100
        return found


class AmitHub:
    """Polls the station in a background loop and tells entities about changes."""

    def __init__(self, hass: HomeAssistant, client: AmitClient, names, interval, host):
        self.hass = hass
        self.client = client
        self.names = names
        self.interval = interval
        self.host = host
        self.data: dict = {}
        self.available = False

    def set_local(self, name: str, value) -> None:
        """Show a just-written value immediately; the next poll confirms it."""
        self.data = {**self.data, name: value}
        async_dispatcher_send(self.hass, SIGNAL)

    async def run(self) -> None:
        loop = asyncio.get_running_loop()
        first = True
        while True:
            started = loop.time()
            delay = self.interval
            if not self.names:  # nothing configured yet
                await asyncio.sleep(1)
                continue
            try:
                new = await self.client.read(self.names)
            except AmitError as exc:
                if self.available or first:
                    _LOGGER.warning("PLC %s not reachable: %s", self.host, exc)
                changed = self.available
                self.available, self.data = False, {}
                delay = max(delay, 1.0)  # do not hammer an offline station
            else:
                if not self.available:
                    _LOGGER.info("PLC %s connected", self.host)
                    missing = [n for n in self.names if n not in new]
                    if missing:
                        _LOGGER.warning(
                            "Variables not found in the PLC: %s", ", ".join(missing)
                        )
                changed = (not self.available) or new != self.data
                self.available, self.data = True, new
            first = False
            if changed:
                async_dispatcher_send(self.hass, SIGNAL)
            await asyncio.sleep(max(0.0, delay - (loop.time() - started)))
