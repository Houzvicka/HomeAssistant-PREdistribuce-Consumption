r"""HDO (low/high tariff) schedule from the public PREdistribuce "Stav HDO" page.

Unlike the consumption export this needs no login: the page at
/cs/potrebuji-zaridit/zakaznici/stav-hdo/ is public and, for a chosen
receiver command code ("povel", printed on the meter / in the contract),
loads the schedule with one AJAX call (found by reading the page's JS,
2026-10-31):

    POST https://www.predistribuce.cz/com/PREdi/UI/Forms/Hdo/HdoForm:hdoMoreDaysAjax
    datum=&povel=<code>&povelTitle=<code>

Response is JSON, `{"html": "<fragment>"}`. The fragment holds one
`hdo-bar` block per group of days (typically Sat-Sun and Mon-Fri blocks
covering about two weeks ahead):

    <div class="blue-text pull-left">pondělí 02.11. - pátek 06.11.</div>
    <span class="hdont"></span>           # hdont = low tariff (NT)
    <span class="span-overflow" title="00:00 - 02:00"></span>
    <span class="hdovt"></span>           # hdovt = high tariff (VT)
    <span class="span-overflow" title="02:00 - 02:40"></span>
    ...

An unknown code returns a `flash error` fragment ("Pro časový interval
neexistují data.") instead of bars. The header has no year, so it is
inferred from a reference date. PRE itself says the plan is informational
only and may change at any time — hence the periodic re-fetch.

No Home Assistant imports here, so this is usable and testable standalone.
"""
from __future__ import annotations

import dataclasses
import datetime
import re

import requests

BASE_URL = "https://www.predistribuce.cz"
HDO_PATH = "/com/PREdi/UI/Forms/Hdo/HdoForm:hdoMoreDaysAjax"

# Same browser-ish headers as api.py; the WAF in front of the portal may care.
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    ),
    "Origin": BASE_URL,
    "Referer": BASE_URL + "/cs/potrebuji-zaridit/zakaznici/stav-hdo/",
    "X-Requested-With": "XMLHttpRequest",
}

_BLOCK_SPLIT = re.compile(r'<div class="hdo-bar">')
_HEADER = re.compile(r'class="blue-text[^"]*">([^<]+)<')
_DATE = re.compile(r"(\d{1,2})\.\s*(\d{1,2})\.")
_BAR = re.compile(
    r'class="(hdont|hdovt)"[^>]*></span>\s*'
    r'<span[^>]*title="(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})"'
)


class HdoError(RuntimeError):
    pass


class HdoNoDataError(HdoError):
    """The portal has no schedule for this command code (typo / unknown)."""


@dataclasses.dataclass(frozen=True)
class Interval:
    """A stretch of constant tariff. `end` is exclusive."""

    start: datetime.datetime
    end: datetime.datetime
    low: bool  # True = low tariff (NT), False = high tariff (VT)


def _post_html(
    path: str, data: dict[str, str], session: requests.Session | None
) -> str:
    http = session or requests.Session()
    resp = http.post(BASE_URL + path, data=data, headers=DEFAULT_HEADERS, timeout=30)
    resp.raise_for_status()
    try:
        return resp.json()["html"]
    except (ValueError, KeyError, TypeError) as err:
        raise HdoError(f"unexpected HDO response shape: {err}") from err


def download_schedule_html(
    command: str, session: requests.Session | None = None
) -> str:
    """Blocking: fetch the HTML fragment for one receiver command code."""
    html = _post_html(
        HDO_PATH, {"datum": "", "povel": command, "povelTitle": command}, session
    )
    if "hdo-bar" not in html:
        raise HdoNoDataError(f"no HDO schedule for command code {command!r}")
    return html


# --- one day, including the past -------------------------------------------
#
# The same page has a one-day endpoint (hdoOneDayAjax, `datum=DD.MM.YYYY`).
# Probed 2026-11-04 with command 605: it answers for past dates back to at
# least 2021 (minute-precise actual switch times such as 04:46, not the
# 20-minute grid of the forecast) and up to ~2 weeks ahead; beyond that it
# returns "Pro časový interval neexistují data. Data jsou k dispozici do ...".
# That history is what lets past consumption be split into NT and VT.

HDO_DAY_PATH = "/com/PREdi/UI/Forms/Hdo/HdoForm:hdoOneDayAjax"
_ANY_BAR = re.compile(r'class="hdo[nv]t"')
_NT_BAR = re.compile(
    r'class="hdont"[^>]*></span>\s*'
    r'<span[^>]*title="(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})"'
)

# Low-tariff stretches of one day as (start_minute, end_minute), wall clock,
# 0..1440, sorted and non-overlapping.
NtMinutes = list[tuple[int, int]]


def download_day_html(
    command: str, day: datetime.date, session: requests.Session | None = None
) -> str:
    """Blocking: the HTML fragment for one command code on one date."""
    html = _post_html(
        HDO_DAY_PATH,
        {"datum": day.strftime("%d.%m.%Y"), "povel": command, "povelTitle": command},
        session,
    )
    if not _ANY_BAR.search(html):
        raise HdoNoDataError(f"no HDO data for command {command!r} on {day}")
    return html


def parse_day_nt(html: str) -> NtMinutes:
    """Low-tariff minute ranges from a one-day fragment (empty = all high)."""
    ranges = sorted(
        (int(h1) * 60 + int(m1), int(h2) * 60 + int(m2))
        for h1, m1, h2, m2 in _NT_BAR.findall(html)
    )
    merged: NtMinutes = []
    for start, end in ranges:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def nt_fraction(
    nt_by_day: dict[datetime.date, NtMinutes],
    start: datetime.datetime,
    end: datetime.datetime,
) -> float:
    """Share (0..1) of the wall-clock span [start, end) spent in low tariff."""
    minutes = (end - start).total_seconds() / 60
    if minutes <= 0:
        raise HdoError(f"empty reading interval {start} - {end}")
    a = start.hour * 60 + start.minute
    b = a + minutes
    overlap = sum(
        max(0.0, min(b, e) - max(a, s)) for s, e in nt_by_day[start.date()]
    )
    return overlap / minutes


def _resolve_date(
    day: int, month: int, near: datetime.date, not_before: datetime.date | None
) -> datetime.date:
    """Pick the year for a day/month so the date lies closest to `near`."""
    candidates = []
    for year in (near.year - 1, near.year, near.year + 1):
        try:
            candidate = datetime.date(year, month, day)
        except ValueError:
            continue
        if not_before is None or candidate >= not_before:
            candidates.append(candidate)
    if not candidates:
        raise HdoError(f"cannot resolve date {day}.{month}.")
    return min(candidates, key=lambda c: abs((c - near).days))


def _at(date: datetime.date, hour: int, minute: int, tz: datetime.tzinfo) -> datetime.datetime:
    # Wall-clock time in `tz`; "24:00" means the next midnight.
    date += datetime.timedelta(days=hour // 24)
    return datetime.datetime.combine(date, datetime.time(hour % 24, minute), tzinfo=tz)


def parse_schedule(
    html: str, tz: datetime.tzinfo, today: datetime.date
) -> list[Interval]:
    """Turn the portal's HTML fragment into merged, time-ordered intervals.

    `today` only anchors the year the header omits. Each block's pattern is
    repeated for every date in its range; neighbouring intervals of the same
    tariff (including across midnight) are merged so interval ends are real
    tariff switches.
    """
    raw: list[Interval] = []
    for block in _BLOCK_SPLIT.split(html)[1:]:
        header = _HEADER.search(block)
        dates = _DATE.findall(header.group(1)) if header else []
        if not dates:
            raise HdoError("HDO block without a parsable date header")
        first = _resolve_date(int(dates[0][0]), int(dates[0][1]), today, None)
        last = (
            _resolve_date(int(dates[1][0]), int(dates[1][1]), first, first)
            if len(dates) > 1
            else first
        )
        bars = [
            (m.group(1) == "hdont", int(m.group(2)), int(m.group(3)),
             int(m.group(4)), int(m.group(5)))
            for m in _BAR.finditer(block)
        ]
        if not bars:
            raise HdoError(f"HDO block {first}..{last} has no intervals")
        day = first
        while day <= last:
            for low, sh, sm, eh, em in bars:
                raw.append(Interval(_at(day, sh, sm, tz), _at(day, eh, em, tz), low))
            day += datetime.timedelta(days=1)

    if not raw:
        raise HdoError("no HDO intervals found in the portal response")

    raw.sort(key=lambda i: i.start)
    merged: list[Interval] = []
    for item in raw:
        if merged and merged[-1].low == item.low and merged[-1].end >= item.start:
            prev = merged[-1]
            merged[-1] = Interval(prev.start, max(prev.end, item.end), prev.low)
        else:
            merged.append(item)
    return merged


def current_interval(
    intervals: list[Interval], now: datetime.datetime
) -> Interval | None:
    for item in intervals:
        if item.start <= now < item.end:
            return item
    return None


def next_start(
    intervals: list[Interval], now: datetime.datetime, low: bool
) -> datetime.datetime | None:
    """Start of the next low (or high) tariff period after `now`."""
    for item in intervals:
        if item.low == low and item.start > now:
            return item.start
    return None


def next_boundary(
    intervals: list[Interval], now: datetime.datetime
) -> datetime.datetime | None:
    """The next moment the tariff (or the schedule's coverage) changes."""
    times = [t for i in intervals for t in (i.start, i.end) if t > now]
    return min(times) if times else None
