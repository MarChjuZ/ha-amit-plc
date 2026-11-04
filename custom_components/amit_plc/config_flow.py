"""Config flow and options flow (add / remove variables from the UI)."""
from __future__ import annotations

import asyncio
import ipaddress
import json
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.components import network
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import (
    CONF_CONTROLLER_NAME,
    CONF_DEVICE_CLASS,
    CONF_INTERVAL_MS,
    CONF_KIND,
    CONF_MAX,
    CONF_MIN,
    CONF_MODEL,
    CONF_NAME,
    CONF_PATH,
    CONF_PRECISION,
    CONF_STEP,
    CONF_UNIT,
    CONF_VARIABLE,
    CONF_VARIABLES,
    DEFAULT_INTERVAL_MS,
    DEFAULT_PATH,
    DEFAULT_PORT,
    DOMAIN,
    KIND_BINARY_SENSOR,
    KIND_NUMBER,
    KIND_SENSOR,
    KIND_SWITCH,
)
from .hub import AmitClient, AmitError

KIND_LABELS = {
    KIND_BINARY_SENSOR: "Input (on/off)",
    KIND_SENSOR: "Number (temperature, pressure, ...)",
    KIND_SWITCH: "Output (on/off, controllable)",
    KIND_NUMBER: "Analog output (slider, e.g. 0-100 %)",
}
DEVICE_CLASSES = [
    "none",
    "temperature",
    "humidity",
    "pressure",
    "voltage",
    "current",
    "power",
    "energy",
    "illuminance",
]
MODEL_VAR = "?IDKey_Type"


async def _probe(host: str, port: int, user: str, password: str) -> str:
    """Connect, read the station type. Raises AmitError."""
    session = aiohttp.ClientSession()
    client = AmitClient(session, f"ws://{host}:{port}{DEFAULT_PATH}", user, password)
    try:
        data = await client.read([MODEL_VAR])
    finally:
        await client.close()
        await session.close()
    if MODEL_VAR not in data:
        raise AmitError("station did not return its type (wrong user/password?)")
    return str(data[MODEL_VAR])


async def _probe_host(session: aiohttp.ClientSession, host: str, port: int) -> str | None:
    """Return the station type, "" if it is a WebSocket device needing a login, None if nothing there."""
    try:
        async with asyncio.timeout(1.5):
            ws = await session.ws_connect(f"ws://{host}:{port}{DEFAULT_PATH}")
            try:
                await ws.send_str(json.dumps({"command": "read-req", "items": [{"name": MODEL_VAR}]}))
                reply = await ws.receive()
            finally:
                await ws.close()
        if reply.type is not aiohttp.WSMsgType.TEXT:
            return None
        data = json.loads(reply.data)
    except (aiohttp.ClientError, OSError, TimeoutError, ValueError):
        return None
    if not isinstance(data, dict) or "command" not in data:
        return None
    for item in data.get("items", []):
        if item.get("name") == MODEL_VAR and item.get("status", 1) == 0:
            return str(item.get("value", ""))
    return ""


async def _local_hosts(hass) -> list[str]:
    """All IPv4 addresses of the local networks (/24 at most), without our own."""
    hosts: list[str] = []
    for adapter in await network.async_get_adapters(hass):
        if not adapter["enabled"]:
            continue
        for ip4 in adapter["ipv4"]:
            prefix = max(int(ip4["network_prefix"]), 24)
            net = ipaddress.ip_network(f"{ip4['address']}/{prefix}", strict=False)
            hosts += [str(h) for h in net.hosts() if str(h) != ip4["address"]]
    return list(dict.fromkeys(hosts))


async def scan_network(hass, port: int, skip: set[str], hosts: list[str] | None = None) -> dict[str, str]:
    """Find AMiT stations on the local network: {host: station type ('' = login needed)}."""
    if hosts is None:
        hosts = await _local_hosts(hass)
    todo = [h for h in hosts if f"{h}:{port}" not in skip]
    sem = asyncio.Semaphore(64)
    found: dict[str, str] = {}
    async with aiohttp.ClientSession() as session:

        async def one(host: str) -> None:
            async with sem:
                res = await _probe_host(session, host, port)
            if res is not None:
                found[host] = res

        await asyncio.gather(*(one(h) for h in todo))
    return dict(sorted(found.items(), key=lambda kv: tuple(int(p) for p in kv[0].split("."))))


def _free() -> NumberSelector:
    """Any decimal number, typed by hand."""
    return NumberSelector(
        NumberSelectorConfig(min=-1000000, max=1000000, step="any", mode=NumberSelectorMode.BOX)
    )


def _num(minimum, maximum) -> NumberSelector:
    return NumberSelector(
        NumberSelectorConfig(min=minimum, max=maximum, step=1, mode=NumberSelectorMode.BOX)
    )


class AmitConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 2

    def __init__(self) -> None:
        self._found: dict[str, str] = {}
        self._port = DEFAULT_PORT
        self._prefill: dict[str, Any] = {}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> AmitOptionsFlow:
        return AmitOptionsFlow()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(step_id="user", menu_options=["scan", "manual"])

    async def async_step_scan(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            self._port = int(user_input[CONF_PORT])
            skip = {e.unique_id for e in self._async_current_entries() if e.unique_id}
            self._found = await scan_network(self.hass, self._port, skip)
            if self._found:
                return await self.async_step_pick()
            errors["base"] = "none_found"
        schema = vol.Schema({vol.Required(CONF_PORT, default=self._port): _num(1, 65535)})
        return self.async_show_form(step_id="scan", data_schema=schema, errors=errors)

    async def async_step_pick(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._prefill = {CONF_HOST: user_input[CONF_HOST], CONF_PORT: self._port}
            return await self.async_step_manual()
        options = [
            {"value": h, "label": f"{h}  ({t or 'WebSocket device, login required'})"}
            for h, t in self._found.items()
        ]
        schema = vol.Schema(
            {
                vol.Required(CONF_HOST): SelectSelector(
                    SelectSelectorConfig(options=options, mode=SelectSelectorMode.LIST)
                )
            }
        )
        return self.async_show_form(
            step_id="pick", data_schema=schema, description_placeholders={"count": str(len(options))}
        )

    async def async_step_manual(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            await self.async_set_unique_id(f"{host}:{int(user_input[CONF_PORT])}")
            self._abort_if_unique_id_configured()
            try:
                model = await _probe(
                    host,
                    int(user_input[CONF_PORT]),
                    user_input.get(CONF_USERNAME, ""),
                    user_input.get(CONF_PASSWORD, ""),
                )
            except AmitError:
                errors["base"] = "cannot_connect"
            else:
                title = (user_input.get(CONF_CONTROLLER_NAME) or "").strip() or f"AMiT PLC {host}"
                return self.async_create_entry(
                    title=title,
                    data={
                        CONF_HOST: host,
                        CONF_PORT: int(user_input[CONF_PORT]),
                        CONF_PATH: DEFAULT_PATH,
                        CONF_USERNAME: user_input.get(CONF_USERNAME, ""),
                        CONF_PASSWORD: user_input.get(CONF_PASSWORD, ""),
                        CONF_INTERVAL_MS: int(user_input[CONF_INTERVAL_MS]),
                        CONF_MODEL: model,
                    },
                )

        defaults = user_input or self._prefill
        schema = vol.Schema(
            {
                vol.Optional(CONF_CONTROLLER_NAME, default=defaults.get(CONF_CONTROLLER_NAME, "")): str,
                vol.Required(CONF_HOST, default=defaults.get(CONF_HOST, "192.168.1.190")): str,
                vol.Required(CONF_PORT, default=defaults.get(CONF_PORT, DEFAULT_PORT)): _num(1, 65535),
                vol.Optional(CONF_USERNAME, default=defaults.get(CONF_USERNAME, "")): str,
                vol.Optional(CONF_PASSWORD, default=defaults.get(CONF_PASSWORD, "")): TextSelector(
                    TextSelectorConfig(type=TextSelectorType.PASSWORD)
                ),
                vol.Required(
                    CONF_INTERVAL_MS, default=defaults.get(CONF_INTERVAL_MS, DEFAULT_INTERVAL_MS)
                ): _num(20, 60000),
            }
        )
        return self.async_show_form(step_id="manual", data_schema=schema, errors=errors)


class AmitOptionsFlow(OptionsFlow):
    """Menu: add variable / remove variable / change interval / save."""

    def __init__(self) -> None:
        self._vars: list[dict] | None = None
        self._interval: int | None = None
        self._plc_vars: dict[str, str] | None = None
        self._pending: str | None = None

    def _load(self) -> None:
        if self._vars is None:
            self._vars = [dict(v) for v in self.config_entry.options.get(CONF_VARIABLES, [])]
            self._interval = int(
                self.config_entry.options.get(
                    CONF_INTERVAL_MS,
                    self.config_entry.data.get(CONF_INTERVAL_MS, DEFAULT_INTERVAL_MS),
                )
            )

    def _persist(self) -> None:
        """Save right away, so closing the dialog never loses changes."""
        self.hass.config_entries.async_update_entry(
            self.config_entry,
            options={CONF_VARIABLES: self._vars, CONF_INTERVAL_MS: self._interval},
        )

    @staticmethod
    def _label(v: dict) -> str:
        return f"{v[CONF_NAME]}  [{v[CONF_VARIABLE]}, {KIND_LABELS[v[CONF_KIND]].split(' (')[0].lower()}]"

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        self._load()
        assert self._vars is not None
        listing = "\n".join(f"• {self._label(v)}" for v in self._vars) or "(no variables yet)"
        options = ["add_variable"]
        if self._vars:
            options.append("remove_variable")
        options += ["interval", "save"]
        return self.async_show_menu(
            step_id="init",
            menu_options=options,
            description_placeholders={"variables": listing, "interval": str(self._interval)},
        )

    async def _plc_variables(self) -> dict[str, str]:
        """Variables read from the PLC (cached for this dialog). Empty if unavailable."""
        if self._plc_vars is None:
            runtime = getattr(self.config_entry, "runtime_data", None)
            try:
                if runtime is not None:
                    self._plc_vars = await runtime.client.dump()
                else:
                    data = self.config_entry.data
                    session = aiohttp.ClientSession()
                    client = AmitClient(
                        session,
                        f"ws://{data[CONF_HOST]}:{data[CONF_PORT]}{data.get(CONF_PATH, DEFAULT_PATH)}",
                        data.get(CONF_USERNAME, ""),
                        data.get(CONF_PASSWORD, ""),
                    )
                    try:
                        self._plc_vars = await client.dump()
                    finally:
                        await client.close()
                        await session.close()
            except AmitError:
                self._plc_vars = {}
        return self._plc_vars

    async def async_step_add_variable(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Step 1: which PLC variable."""
        assert self._vars is not None
        errors: dict[str, str] = {}
        if user_input is not None:
            variable = user_input[CONF_VARIABLE].strip()
            if not variable:
                errors["base"] = "empty"
            else:
                self._pending = variable
                return await self.async_step_details()

        plc_vars = await self._plc_variables()
        used = {v[CONF_VARIABLE] for v in self._vars}
        choices = [
            {"value": n, "label": f"{n} ({t})"}
            for n, t in sorted(plc_vars.items())
            if n not in used and not n.startswith("?")
        ]
        if choices:
            field: Any = SelectSelector(
                SelectSelectorConfig(options=choices, custom_value=True, mode=SelectSelectorMode.DROPDOWN)
            )
        else:
            field = str
        schema = vol.Schema({vol.Required(CONF_VARIABLE, default=""): field})
        return self.async_show_form(
            step_id="add_variable",
            data_schema=schema,
            errors=errors,
            description_placeholders={"count": str(len(choices))},
        )

    async def async_step_details(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Step 2: type, name, unit."""
        assert self._vars is not None and self._pending
        errors: dict[str, str] = {}
        variable = self._pending
        if user_input is not None:
            name = user_input[CONF_NAME].strip()
            kind = user_input[CONF_KIND]
            if not name:
                errors["base"] = "empty"
            elif kind == KIND_NUMBER and (
                float(user_input.get(CONF_MIN, 0)) >= float(user_input.get(CONF_MAX, 100))
                or float(user_input.get(CONF_STEP, 1)) <= 0
            ):
                errors["base"] = "bad_range"
            elif any(v[CONF_VARIABLE] == variable and v[CONF_KIND] == kind for v in self._vars):
                errors["base"] = "duplicate"
            else:
                dev_class = user_input.get(CONF_DEVICE_CLASS, "none")
                self._vars.append(
                    {
                        CONF_KIND: kind,
                        CONF_NAME: name,
                        CONF_VARIABLE: variable,
                        CONF_UNIT: user_input.get(CONF_UNIT, "").strip(),
                        CONF_DEVICE_CLASS: None if dev_class == "none" else dev_class,
                        CONF_PRECISION: int(user_input.get(CONF_PRECISION, 1)),
                        CONF_MIN: float(user_input.get(CONF_MIN, 0)),
                        CONF_MAX: float(user_input.get(CONF_MAX, 100)),
                        CONF_STEP: float(user_input.get(CONF_STEP, 1)),
                    }
                )
                self._pending = None
                self._persist()
                return await self.async_step_init()

        vtype = (self._plc_vars or {}).get(variable, "")
        d = user_input or {}
        default_kind = d.get(CONF_KIND, KIND_BINARY_SENSOR if vtype == "BOOL" else KIND_SENSOR)
        schema = vol.Schema(
            {
                vol.Required(CONF_KIND, default=default_kind): SelectSelector(
                    SelectSelectorConfig(
                        options=[{"value": k, "label": l} for k, l in KIND_LABELS.items()],
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Required(CONF_NAME, default=d.get(CONF_NAME, variable)): str,
                vol.Optional(CONF_UNIT, default=d.get(CONF_UNIT, "")): str,
                vol.Optional(CONF_DEVICE_CLASS, default=d.get(CONF_DEVICE_CLASS, "none")): SelectSelector(
                    SelectSelectorConfig(options=DEVICE_CLASSES, mode=SelectSelectorMode.DROPDOWN)
                ),
                vol.Optional(CONF_PRECISION, default=d.get(CONF_PRECISION, 1)): _num(0, 6),
                vol.Optional(CONF_MIN, default=d.get(CONF_MIN, 0)): _free(),
                vol.Optional(CONF_MAX, default=d.get(CONF_MAX, 100)): _free(),
                vol.Optional(CONF_STEP, default=d.get(CONF_STEP, 1)): _free(),
            }
        )
        return self.async_show_form(
            step_id="details",
            data_schema=schema,
            errors=errors,
            description_placeholders={"variable": variable, "type": vtype or "?"},
        )

    async def async_step_remove_variable(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        assert self._vars is not None
        if user_input is not None:
            drop = {int(i) for i in user_input.get("remove", [])}
            self._vars = [v for i, v in enumerate(self._vars) if i not in drop]
            self._persist()
            return await self.async_step_init()
        schema = vol.Schema(
            {
                vol.Required("remove", default=[]): SelectSelector(
                    SelectSelectorConfig(
                        options=[{"value": str(i), "label": self._label(v)} for i, v in enumerate(self._vars)],
                        multiple=True,
                        mode=SelectSelectorMode.LIST,
                    )
                )
            }
        )
        return self.async_show_form(step_id="remove_variable", data_schema=schema)

    async def async_step_interval(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._interval = int(user_input[CONF_INTERVAL_MS])
            self._persist()
            return await self.async_step_init()
        schema = vol.Schema(
            {vol.Required(CONF_INTERVAL_MS, default=self._interval): _num(20, 60000)}
        )
        return self.async_show_form(step_id="interval", data_schema=schema)

    async def async_step_save(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_create_entry(
            title="", data={CONF_VARIABLES: self._vars, CONF_INTERVAL_MS: self._interval}
        )
