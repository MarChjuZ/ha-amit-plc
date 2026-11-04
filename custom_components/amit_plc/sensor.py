from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)

from .const import (
    CONF_DEVICE_CLASS,
    CONF_KIND,
    CONF_NAME,
    CONF_PRECISION,
    CONF_UNIT,
    CONF_VARIABLE,
    KIND_SENSOR,
)
from .entity import AmitEntity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities(
        AmitSensor(entry, v)
        for v in entry.runtime_data.variables
        if v[CONF_KIND] == KIND_SENSOR
    )


class AmitSensor(AmitEntity, SensorEntity):
    def __init__(self, entry, cfg):
        super().__init__(entry, cfg[CONF_NAME], cfg[CONF_VARIABLE], "sensor")
        self._precision = int(cfg.get(CONF_PRECISION, 1))
        self._attr_native_unit_of_measurement = cfg.get(CONF_UNIT) or None
        dev_class = cfg.get(CONF_DEVICE_CLASS)
        self._attr_device_class = SensorDeviceClass(dev_class) if dev_class else None
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self):
        val = self._raw
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            return val
        return round(val, self._precision)
