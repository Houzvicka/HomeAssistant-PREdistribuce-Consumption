"""Parse a PREdistribuce "Profily spotřeby" CSV export.

Format observed from both a manual portal export and the api.py-driven one:
semicolon-delimited, ISO-8859-2 encoded, CRLF line endings, Czech decimal
commas, header row naming the meter (EAN) and columns:

    Počátek intervalu;Konec intervalu;<EAN> - Činná - spotřeba [kWh];<EAN> - Činný - výkon [kW];

Data rows, 15-minute intervals:

    01.08.2026 00:00;01.08.2026 00:15;0,030;0,120;
"""
from __future__ import annotations

import datetime
from collections.abc import Callable
from dataclasses import dataclass


@dataclass
class Reading:
    start: datetime.datetime
    end: datetime.datetime
    kwh: float
    kw: float


def _parse_dt(s: str) -> datetime.datetime:
    return datetime.datetime.strptime(s, "%d.%m.%Y %H:%M")


def parse(raw: bytes, encoding: str = "iso-8859-2") -> list[Reading]:
    text = raw.decode(encoding)
    lines = [l for l in text.splitlines() if l.strip()]
    if not lines:
        return []

    readings: list[Reading] = []
    for line in lines[1:]:  # skip header
        parts = line.split(";")
        if len(parts) < 4:
            continue
        start_s, end_s, kwh_s, kw_s = parts[0], parts[1], parts[2], parts[3]
        if not start_s or not kwh_s:
            continue
        readings.append(
            Reading(
                start=_parse_dt(start_s),
                end=_parse_dt(end_s),
                kwh=float(kwh_s.replace(",", ".")),
                kw=float(kw_s.replace(",", ".")) if kw_s else 0.0,
            )
        )
    return readings


def to_hourly_kwh(readings: list[Reading]) -> dict[datetime.datetime, float]:
    """Sum 15-minute kWh readings into hourly buckets (hour-start keys).

    This is what Home Assistant's long-term statistics need — see
    async_add_external_statistics, which only accepts hour-aligned timestamps.
    """
    hourly: dict[datetime.datetime, float] = {}
    for r in readings:
        bucket = r.start.replace(minute=0, second=0, microsecond=0)
        hourly[bucket] = hourly.get(bucket, 0.0) + r.kwh
    return hourly


def to_hourly_kwh_utc(
    readings: list[Reading], tz: datetime.tzinfo
) -> dict[datetime.datetime, float]:
    """Like to_hourly_kwh, but keyed by tz-aware UTC hour starts.

    The export carries naive local times, so the autumn DST change repeats
    02:00-03:00. Readings arrive in chronological order, so a start that
    does not advance past the previous one is the second pass (fold=1).
    Not yet verified against a real export from a DST-change day.
    """
    hourly: dict[datetime.datetime, float] = {}
    for r, bucket in _utc_buckets(readings, tz):
        hourly[bucket] = hourly.get(bucket, 0.0) + r.kwh
    return hourly


def _utc_buckets(readings: list[Reading], tz: datetime.tzinfo):
    """Yield (reading, tz-aware UTC hour start), resolving the DST fold."""
    prev: datetime.datetime | None = None
    fold = 0
    for r in readings:
        if prev is not None and r.start <= prev:
            fold = 1
        elif prev is not None and r.start > prev and fold and r.start.hour != prev.hour:
            # moved past the repeated hour; later wall times are unambiguous
            fold = 0
        prev = r.start
        local = r.start.replace(minute=0, second=0, microsecond=0, tzinfo=tz, fold=fold)
        yield r, local.astimezone(datetime.timezone.utc)


def to_hourly_kwh_utc_split(
    readings: list[Reading],
    tz: datetime.tzinfo,
    nt_share: Callable[[Reading], float],
) -> tuple[dict[datetime.datetime, float], dict[datetime.datetime, float]]:
    """Hourly (NT, VT) kWh, UTC-keyed. nt_share(reading) is its low-tariff
    fraction (0..1); NT + VT of every reading equals its kWh."""
    nt: dict[datetime.datetime, float] = {}
    vt: dict[datetime.datetime, float] = {}
    for r, bucket in _utc_buckets(readings, tz):
        share = nt_share(r)
        nt[bucket] = nt.get(bucket, 0.0) + r.kwh * share
        vt[bucket] = vt.get(bucket, 0.0) + r.kwh * (1.0 - share)
    return nt, vt
