"""Coordinator for the public HDO schedule (no login involved)."""
from __future__ import annotations

import logging
from zoneinfo import ZoneInfo

import requests

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import DOMAIN, HDO_UPDATE_INTERVAL, PORTAL_TIMEZONE
from .hdo import HdoError, Interval, download_schedule_html, parse_schedule

_LOGGER = logging.getLogger(__name__)


class HdoCoordinator(DataUpdateCoordinator[list[Interval]]):
    """Data is the merged, time-ordered tariff schedule (~2 weeks ahead)."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, command: str) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}_hdo",
            update_interval=HDO_UPDATE_INTERVAL,
        )
        self.command = command
        self._tz = ZoneInfo(PORTAL_TIMEZONE)

    async def _async_update_data(self) -> list[Interval]:
        try:
            html = await self.hass.async_add_executor_job(
                download_schedule_html, self.command
            )
            today = dt_util.now(self._tz).date()
            return parse_schedule(html, self._tz, today)
        except requests.RequestException as err:
            raise UpdateFailed(f"Cannot reach the HDO page: {err}") from err
        except HdoError as err:
            raise UpdateFailed(f"HDO schedule for {self.command}: {err}") from err
