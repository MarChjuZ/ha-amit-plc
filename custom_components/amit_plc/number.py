from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode

from .const import (
    CONF_KIND,
    CONF_MAX,
    CONF_MIN,
    CONF_NAME,
    CONF_PRECISION,
    CONF_STEP,
    CONF_UNIT,
    CONF_VARIABLE,
    KIND_NUMBER,
)
from .entity import AmitEntity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities(
        AmitNumber(entry, v)
        for v in entry.runtime_data.variables
        if v[CONF_KIND] == KIND_NUMBER
    )


class AmitNumber(AmitEntity, NumberEntity):
    """Analog output: slider between a hand-entered minimum and maximum."""

    _attr_mode = NumberMode.SLIDER

    def __init__(self, entry, cfg):
        super().__init__(entry, cfg[CONF_NAME], cfg[CONF_VARIABLE], "number")
        self._client = entry.runtime_data.client
        self._attr_native_min_value = float(cfg.get(CONF_MIN, 0))
        self._attr_native_max_value = float(cfg.get(CONF_MAX, 100))
        self._attr_native_step = float(cfg.get(CONF_STEP, 1))
        self._attr_native_unit_of_measurement = cfg.get(CONF_UNIT) or None
        self._precision = int(cfg.get(CONF_PRECISION, 1))

    @property
    def native_value(self):
        val = self._raw
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            return None
        return round(val, self._precision)

    async def async_set_native_value(self, value: float) -> None:
        out = int(value) if float(value).is_integer() else float(value)
        await self._client.write(self._variable, out)
        self._hub.set_local(self._variable, out)
