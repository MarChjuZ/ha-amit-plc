"""Config flow and options flow (add / remove variables from the UI)."""
from __future__ import annotations

from typing import Any

import aiohttp
import voluptuous as vol

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
    CONF_DEVICE_CLASS,
    CONF_INTERVAL_MS,
    CONF_KIND,
    CONF_MODEL,
    CONF_NAME,
    CONF_PATH,
    CONF_PRECISION,
    CONF_UNIT,
    CONF_VARIABLE,
    CONF_VARIABLES,
    DEFAULT_INTERVAL_MS,
    DEFAULT_PATH,
    DEFAULT_PORT,
    DOMAIN,
    KIND_BINARY_SENSOR,
    KIND_SENSOR,
    KIND_SWITCH,
)
from .hub import AmitClient, AmitError

KIND_LABELS = {
    KIND_BINARY_SENSOR: "Input (on/off)",
    KIND_SENSOR: "Number (temperature, pressure, ...)",
    KIND_SWITCH: "Output (on/off, controllable)",
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


def _num(minimum, maximum) -> NumberSelector:
    return NumberSelector(
        NumberSelectorConfig(min=minimum, max=maximum, step=1, mode=NumberSelectorMode.BOX)
    )


class AmitConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> AmitOptionsFlow:
        return AmitOptionsFlow()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            await self.async_set_unique_id(host)
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
                return self.async_create_entry(
                    title=f"AMiT PLC {host}",
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

        defaults = user_input or {}
        schema = vol.Schema(
            {
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
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)


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
                    }
                )
                self._pending = None
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
            return await self.async_step_init()
        schema = vol.Schema(
            {vol.Required(CONF_INTERVAL_MS, default=self._interval): _num(20, 60000)}
        )
        return self.async_show_form(step_id="interval", data_schema=schema)

    async def async_step_save(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_create_entry(
            title="", data={CONF_VARIABLES: self._vars, CONF_INTERVAL_MS: self._interval}
        )
