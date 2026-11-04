"""AMiT PLC (WebSocket JSON) - fast polling over one persistent connection."""
from __future__ import annotations

from dataclasses import dataclass

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import (
    CONF_INTERVAL_MS,
    CONF_PATH,
    CONF_VARIABLE,
    CONF_VARIABLES,
    DEFAULT_INTERVAL_MS,
    DEFAULT_PATH,
    DOMAIN,
    PLATFORMS,
)
from .hub import AmitClient, AmitHub

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


@dataclass
class AmitRuntime:
    session: aiohttp.ClientSession
    client: AmitClient
    hub: AmitHub
    variables: list


type AmitConfigEntry = ConfigEntry[AmitRuntime]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    return True


async def async_setup_entry(hass: HomeAssistant, entry: AmitConfigEntry) -> bool:
    data = entry.data
    variables = list(entry.options.get(CONF_VARIABLES, []))
    interval_ms = entry.options.get(
        CONF_INTERVAL_MS, data.get(CONF_INTERVAL_MS, DEFAULT_INTERVAL_MS)
    )
    session = aiohttp.ClientSession()
    client = AmitClient(
        session,
        f"ws://{data[CONF_HOST]}:{data[CONF_PORT]}{data.get(CONF_PATH, DEFAULT_PATH)}",
        data.get(CONF_USERNAME, ""),
        data.get(CONF_PASSWORD, ""),
    )
    names = sorted({v[CONF_VARIABLE] for v in variables})
    hub = AmitHub(hass, client, names, interval_ms / 1000, data[CONF_HOST])
    entry.runtime_data = AmitRuntime(session, client, hub, variables)

    entry.async_create_background_task(hass, hub.run(), "amit_plc poll loop")
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_reload_on_change))
    return True


async def _reload_on_change(hass: HomeAssistant, entry: AmitConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: AmitConfigEntry) -> bool:
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok:
        await entry.runtime_data.client.close()
        await entry.runtime_data.session.close()
    return ok
