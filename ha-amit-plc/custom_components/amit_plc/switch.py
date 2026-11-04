from __future__ import annotations

from homeassistant.components.switch import SwitchEntity

from .const import CONF_KIND, CONF_NAME, CONF_VARIABLE, KIND_SWITCH
from .entity import AmitEntity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities(
        AmitSwitch(entry, v[CONF_NAME], v[CONF_VARIABLE])
        for v in entry.runtime_data.variables
        if v[CONF_KIND] == KIND_SWITCH
    )


class AmitSwitch(AmitEntity, SwitchEntity):
    def __init__(self, entry, name, variable):
        super().__init__(entry, name, variable, "switch")
        self._client = entry.runtime_data.client

    @property
    def is_on(self):
        return None if self._raw is None else bool(self._raw)

    async def _set(self, value: bool) -> None:
        await self._client.write(self._variable, value)
        self._hub.set_local(self._variable, value)

    async def async_turn_on(self, **kwargs) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._set(False)
