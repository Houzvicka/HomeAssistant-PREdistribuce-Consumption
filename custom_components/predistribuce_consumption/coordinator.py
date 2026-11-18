"""DataUpdateCoordinator: login -> download -> parse -> push statistics."""
from __future__ import annotations

import datetime
import logging
import time
from zoneinfo import ZoneInfo

import requests

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import NoDataError, PortalClient, PortalError
from .const import (
    CONF_BACKFILL_DAYS,
    CONF_EAN,
    CONF_HDO_HISTORY_DAYS,
    CONF_PRICE_NT,
    CONF_PRICE_VT,
    COST_SUFFIX,
    DEFAULT_BACKFILL_DAYS,
    DEFAULT_HDO_HISTORY_DAYS,
    DOMAIN,
    PORTAL_TIMEZONE,
    REFETCH_DAYS,
    SUFFIX_NT,
    SUFFIX_VT,
    UPDATE_INTERVAL,
    get_hdo_command,
    get_price,
)
from .hdo import (
    HdoError,
    NtMinutes,
    download_day_html,
    nt_fraction,
    parse_day_nt,
)
from .parser import Reading, parse, to_hourly_kwh_utc, to_hourly_kwh_utc_split
from .statistics import async_insert, async_insert_cost, async_last_stat_start

_LOGGER = logging.getLogger(__name__)


def _fetch(
    username: str,
    password: str,
    ean: str,
    date_from: datetime.date,
    date_to: datetime.date,
) -> bytes | None:
    """Blocking: fresh login + export. None means the portal has no data."""
    client = PortalClient()
    client.login(username, password)
    try:
        return client.download_export(ean, date_from, date_to)
    except NoDataError:
        return None


def _fetch_day_schedules(
    command: str,
    days: list[datetime.date],
    cache: dict[datetime.date, NtMinutes],
) -> dict[datetime.date, NtMinutes]:
    """Blocking: low-tariff minutes per day; cached days are not refetched.

    One polite request per uncached day (a 4-month backfill is ~120 of them,
    once; afterwards a normal run needs only the last few days).
    """
    session = requests.Session()
    out: dict[datetime.date, NtMinutes] = {}
    for day in days:
        if day not in cache:
            cache[day] = parse_day_nt(download_day_html(command, day, session))
            time.sleep(0.2)
        out[day] = cache[day]
    return out


class PortalCoordinator(DataUpdateCoordinator[datetime.date | None]):
    """Data is the newest day imported so far (None until something is)."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
        )
        self._tz = ZoneInfo(PORTAL_TIMEZONE)
        # Schedules of days old enough to be settled; lost on restart (cheap).
        self._day_cache: dict[datetime.date, NtMinutes] = {}

    async def _async_split_from(
        self, ean: str, yesterday: datetime.date
    ) -> datetime.date:
        """First day the NT/VT statistics still need (re)writing."""
        last_nt = await async_last_stat_start(self.hass, ean, SUFFIX_NT)
        # A price added later needs its cost statistic built over the history.
        for suffix, key in ((SUFFIX_NT, CONF_PRICE_NT), (SUFFIX_VT, CONF_PRICE_VT)):
            if get_price(self.config_entry, key) and (
                await async_last_stat_start(self.hass, ean, suffix + COST_SUFFIX)
                is None
            ):
                last_nt = None
        if last_nt is None:
            days = self.config_entry.options.get(
                CONF_HDO_HISTORY_DAYS, DEFAULT_HDO_HISTORY_DAYS
            )
            return yesterday - datetime.timedelta(days=days - 1)
        last_day = last_nt.astimezone(self._tz).date()
        return min(last_day - datetime.timedelta(days=REFETCH_DAYS), yesterday)

    async def _async_import_split(
        self,
        ean: str,
        command: str,
        readings: list[Reading],
        split_from: datetime.date,
        yesterday: datetime.date,
    ) -> None:
        """Write the NT/VT statistics; on failure keep the total and retry later."""
        subset = [r for r in readings if r.start.date() >= split_from]
        if not subset:
            return
        days = sorted({r.start.date() for r in subset})
        try:
            nt_by_day = await self.hass.async_add_executor_job(
                _fetch_day_schedules, command, days, self._day_cache
            )
        except (HdoError, requests.RequestException) as err:
            _LOGGER.warning("NT/VT split skipped this run: %s", err)
            return
        settled = yesterday - datetime.timedelta(days=REFETCH_DAYS + 1)
        for day in [d for d in self._day_cache if d > settled]:
            del self._day_cache[day]  # recent days may still be corrected
        nt, vt = to_hourly_kwh_utc_split(
            subset, self._tz, lambda r: nt_fraction(nt_by_day, r.start, r.end)
        )
        await async_insert(self.hass, ean, nt, SUFFIX_NT)
        await async_insert(self.hass, ean, vt, SUFFIX_VT)
        for suffix, kwh, key in (
            (SUFFIX_NT, nt, CONF_PRICE_NT),
            (SUFFIX_VT, vt, CONF_PRICE_VT),
        ):
            price = get_price(self.config_entry, key)
            if price:
                await async_insert_cost(self.hass, ean, kwh, suffix, price)
        _LOGGER.info(
            "Imported NT/VT split for %s (%s to %s): %.2f kWh NT, %.2f kWh VT",
            ean,
            days[0],
            days[-1],
            sum(nt.values()),
            sum(vt.values()),
        )

    async def _async_update_data(self) -> datetime.date | None:
        ean = self.config_entry.data[CONF_EAN]
        # The portal lags a day and zero-fills today, so never ask for today.
        yesterday = datetime.datetime.now(self._tz).date() - datetime.timedelta(days=1)

        last_start = await async_last_stat_start(self.hass, ean)
        if last_start is None:
            backfill = self.config_entry.data.get(
                CONF_BACKFILL_DAYS, DEFAULT_BACKFILL_DAYS
            )
            date_from = yesterday - datetime.timedelta(days=backfill - 1)
        else:
            last_day = last_start.astimezone(self._tz).date()
            date_from = min(last_day - datetime.timedelta(days=REFETCH_DAYS), yesterday)

        command = get_hdo_command(self.config_entry)
        split_from: datetime.date | None = None
        if command:
            split_from = await self._async_split_from(ean, yesterday)
            date_from = min(date_from, split_from)

        _LOGGER.debug("Fetching %s from %s to %s", ean, date_from, yesterday)
        try:
            raw = await self.hass.async_add_executor_job(
                _fetch,
                self.config_entry.data[CONF_USERNAME],
                self.config_entry.data[CONF_PASSWORD],
                ean,
                date_from,
                yesterday,
            )
        except PortalError as err:
            # Bad credentials and a reCAPTCHA block look the same from here.
            raise ConfigEntryAuthFailed(str(err)) from err
        except requests.RequestException as err:
            raise UpdateFailed(f"Cannot reach the portal: {err}") from err

        if raw is None:
            _LOGGER.info("Portal has no data for %s to %s yet", date_from, yesterday)
            return self.data

        readings = parse(raw)
        hourly = to_hourly_kwh_utc(readings, self._tz)
        written = await async_insert(self.hass, ean, hourly)
        _LOGGER.info(
            "Imported %d hourly statistics for %s (%s to %s)",
            written,
            ean,
            date_from,
            yesterday,
        )
        if command and split_from is not None:
            await self._async_import_split(ean, command, readings, split_from, yesterday)
        if not hourly:
            return self.data
        return max(hourly).astimezone(self._tz).date()
