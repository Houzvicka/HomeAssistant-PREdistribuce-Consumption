"""PREdistribuce consumption: portal export -> recorder external statistics.

Optionally also exposes the HDO (low/high tariff) schedule when a receiver
command code is configured.
"""
from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import get_hdo_command
from .coordinator import PortalCoordinator
from .hdo_coordinator import HdoCoordinator

PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR]


@dataclass
class PortalRuntimeData:
    portal: PortalCoordinator
    hdo: HdoCoordinator | None = None


type PortalConfigEntry = ConfigEntry[PortalRuntimeData]


async def async_setup_entry(hass: HomeAssistant, entry: PortalConfigEntry) -> bool:
    portal = PortalCoordinator(hass, entry)
    await portal.async_config_entry_first_refresh()

    hdo: HdoCoordinator | None = None
    command = get_hdo_command(entry)
    if command:
        hdo = HdoCoordinator(hass, entry, command)
        # Plain refresh, not first_refresh: HDO is a bonus, so a failure here
        # must not stop the consumption import. Entities stay unavailable
        # until the next successful (6-hourly) refresh.
        await hdo.async_refresh()

    entry.runtime_data = PortalRuntimeData(portal, hdo)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: PortalConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
