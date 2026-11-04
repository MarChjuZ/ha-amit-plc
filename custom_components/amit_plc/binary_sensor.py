from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity

from .const import CONF_KIND, CONF_NAME, CONF_VARIABLE, KIND_BINARY_SENSOR
from .entity import AmitEntity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities(
        AmitBinarySensor(entry, v[CONF_NAME], v[CONF_VARIABLE])
        for v in entry.runtime_data.variables
        if v[CONF_KIND] == KIND_BINARY_SENSOR
    )


class AmitBinarySensor(AmitEntity, BinarySensorEntity):
    def __init__(self, entry, name, variable):
        super().__init__(entry, name, variable, "binary_sensor")

    @property
    def is_on(self):
        return None if self._raw is None else bool(self._raw)
