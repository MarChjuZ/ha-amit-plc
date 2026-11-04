"""Shared base entity."""
from __future__ import annotations

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity

from .const import CONF_MODEL, DOMAIN, SIGNAL


class AmitEntity(Entity):
    _attr_should_poll = False

    def __init__(self, entry, name: str, variable: str, kind: str) -> None:
        self._hub = entry.runtime_data.hub
        self._variable = variable
        self._attr_name = name
        self._attr_unique_id = f"{entry.entry_id}_{kind}_{variable}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="AMiT",
            model=entry.data.get(CONF_MODEL) or None,
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL, self._handle_update)
        )

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()

    @property
    def _raw(self):
        return self._hub.data.get(self._variable)

    @property
    def available(self) -> bool:
        return self._hub.available and self._variable in self._hub.data
