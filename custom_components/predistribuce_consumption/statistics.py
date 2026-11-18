"""Push hourly consumption into the recorder as external statistics."""
from __future__ import annotations

import datetime

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import (
    StatisticData,
    StatisticMeanType,
    StatisticMetaData,
)
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    get_last_statistics,
    statistics_during_period,
)
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant

from .const import COST_CURRENCY, COST_SUFFIX, DOMAIN, STAT_LABELS, UNIT_CLASS_ENERGY


def statistic_id(ean: str, suffix: str = "") -> str:
    return f"{DOMAIN}:{ean}{suffix}"


async def async_last_stat_start(
    hass: HomeAssistant, ean: str, suffix: str = ""
) -> datetime.datetime | None:
    """Start (UTC) of the newest imported hour, or None if nothing yet."""
    sid = statistic_id(ean, suffix)
    last = await get_instance(hass).async_add_executor_job(
        get_last_statistics, hass, 1, sid, True, {"sum"}
    )
    rows = last.get(sid)
    if not rows:
        return None
    return datetime.datetime.fromtimestamp(rows[0]["start"], datetime.timezone.utc)


async def _async_sum_before(
    hass: HomeAssistant, sid: str, first_hour: datetime.datetime
) -> float:
    """Cumulative sum at the hour just before first_hour (0 if none)."""
    prev = first_hour - datetime.timedelta(hours=1)
    found = await get_instance(hass).async_add_executor_job(
        statistics_during_period,
        hass,
        prev,
        first_hour,
        {sid},
        "hour",
        None,
        {"sum"},
    )
    rows = found.get(sid)
    if not rows:
        return 0.0
    return float(rows[0].get("sum") or 0.0)


async def async_insert(
    hass: HomeAssistant,
    ean: str,
    hourly_kwh: dict[datetime.datetime, float],
    suffix: str = "",
) -> int:
    """Write hourly kWh as cumulative external statistics; return rows written.

    hourly_kwh keys must be tz-aware, hour-aligned. The cumulative sum is
    seeded from the hour before the first one written, so re-importing an
    overlapping window rewrites those hours consistently.
    """
    return await _async_write(
        hass,
        statistic_id(ean, suffix),
        f"PREdistribuce consumption {ean}{STAT_LABELS[suffix]}",
        hourly_kwh,
        UNIT_CLASS_ENERGY,
        UnitOfEnergy.KILO_WATT_HOUR,
    )


async def async_insert_cost(
    hass: HomeAssistant,
    ean: str,
    hourly_kwh: dict[datetime.datetime, float],
    suffix: str,
    price: float,
) -> int:
    """Write the cost (kWh x price, CZK) of a tariff as a cumulative statistic.

    The statistic id is "<ean><suffix>_cost". Hours rewritten by a later run
    are priced at the price configured then; older hours keep theirs.
    """
    cost_suffix = suffix + COST_SUFFIX
    return await _async_write(
        hass,
        statistic_id(ean, cost_suffix),
        f"PREdistribuce consumption {ean}{STAT_LABELS[cost_suffix]}",
        {hour: kwh * price for hour, kwh in hourly_kwh.items()},
        None,
        COST_CURRENCY,
    )


async def _async_write(
    hass: HomeAssistant,
    sid: str,
    name: str,
    values: dict[datetime.datetime, float],
    unit_class: str | None,
    unit: str,
) -> int:
    if not values:
        return 0
    hours = sorted(values)
    running = await _async_sum_before(hass, sid, hours[0])

    stats: list[StatisticData] = []
    for hour in hours:
        running += values[hour]
        stats.append(StatisticData(start=hour, state=values[hour], sum=running))

    metadata = StatisticMetaData(
        mean_type=StatisticMeanType.NONE,
        has_sum=True,
        name=name,
        source=DOMAIN,
        statistic_id=sid,
        unit_class=unit_class,
        unit_of_measurement=unit,
    )
    async_add_external_statistics(hass, metadata, stats)
    return len(stats)
