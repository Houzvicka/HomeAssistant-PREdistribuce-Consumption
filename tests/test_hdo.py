"""Offline tests for hdo.py. Run: python -m unittest discover tests"""
import datetime
import json
import os
import sys
import unittest

HERE = os.path.dirname(__file__)
sys.path.insert(
    0,
    os.path.join(HERE, "..", "custom_components", "predistribuce_consumption"),
)

import hdo  # noqa: E402
from hdo import (  # noqa: E402
    HdoError,
    current_interval,
    next_boundary,
    next_start,
    nt_fraction,
    parse_day_nt,
    parse_schedule,
)
from parser import Reading, to_hourly_kwh_utc, to_hourly_kwh_utc_split  # noqa: E402

# Fixed +01:00 stands in for ZoneInfo (Windows has no tzdata); hdo.py only
# needs a tzinfo. DST handling is ZoneInfo's job, not the parser's.
TZ = datetime.timezone(datetime.timedelta(hours=1))


def _bars(*spec):
    """spec: (tariff 'nt'|'vt', 'HH:MM - HH:MM') -> bar markup like the portal's."""
    out = []
    for tariff, title in spec:
        out.append(f'<span style="left: 0%;" class="hdo{tariff}"></span>')
        out.append(
            f'<span style="left: 0%;" class="span-overflow" title="{title}"></span>'
        )
    return "\n".join(out)


def _block(header, *spec):
    return (
        f'<div class="hdo-bar"><div class="blue-text pull-left">{header}</div>'
        f'<div class="overflow-bar"></div>{_bars(*spec)}</div>'
    )


class RealFixtureTest(unittest.TestCase):
    """The response captured from the live portal (command 605, 2026-10-31)."""

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(HERE, "fixtures", "hdo_605.json"), encoding="utf-8") as f:
            cls.html = json.load(f)["html"]
        cls.today = datetime.date(2026, 10, 31)
        cls.intervals = parse_schedule(cls.html, TZ, cls.today)

    def test_covers_all_four_blocks(self):
        days = {i.start.date() for i in self.intervals}
        self.assertEqual(min(days), datetime.date(2026, 10, 31))
        self.assertEqual(max(days), datetime.date(2026, 11, 13))
        self.assertEqual(len(days), 14)  # 31.10.-13.11. with no gaps

    def test_sorted_contiguous_and_alternating(self):
        for a, b in zip(self.intervals, self.intervals[1:]):
            self.assertEqual(a.end, b.start)  # no gaps or overlaps
            self.assertNotEqual(a.low, b.low)  # same-tariff neighbours merged

    def test_saturday_midnight_start_is_low_tariff(self):
        # 31.10. starts with NT 00:00-02:00 in the fixture.
        first = self.intervals[0]
        self.assertTrue(first.low)
        self.assertEqual(first.start, datetime.datetime(2026, 10, 31, 0, 0, tzinfo=TZ))
        self.assertEqual(first.end, datetime.datetime(2026, 10, 31, 2, 0, tzinfo=TZ))

    def test_last_interval_ends_at_midnight(self):
        self.assertEqual(
            self.intervals[-1].end, datetime.datetime(2026, 11, 14, 0, 0, tzinfo=TZ)
        )

    def test_lookups(self):
        now = datetime.datetime(2026, 10, 31, 1, 0, tzinfo=TZ)
        cur = current_interval(self.intervals, now)
        self.assertTrue(cur.low)
        self.assertEqual(next_boundary(self.intervals, now), cur.end)
        self.assertEqual(
            next_start(self.intervals, now, low=False),
            datetime.datetime(2026, 10, 31, 2, 0, tzinfo=TZ),
        )
        self.assertEqual(
            next_start(self.intervals, now, low=True),
            datetime.datetime(2026, 10, 31, 2, 40, tzinfo=TZ),
        )


class ParseEdgeCasesTest(unittest.TestCase):
    def test_midnight_merge_across_days(self):
        html = _block(
            "pondělí 02.11. - úterý 03.11.",
            ("nt", "00:00 - 02:00"),
            ("vt", "02:00 - 22:00"),
            ("nt", "22:00 - 24:00"),
        )
        got = parse_schedule(html, TZ, datetime.date(2026, 11, 1))
        # Mon 22:00 NT runs straight into Tue 00:00-02:00 NT: one 4 h interval.
        merged = [i for i in got if i.low and i.start.day == 2 and i.start.hour == 22]
        self.assertEqual(len(merged), 1)
        self.assertEqual(
            merged[0].end, datetime.datetime(2026, 11, 3, 2, 0, tzinfo=TZ)
        )

    def test_single_day_header(self):
        html = _block("středa 04.11.", ("nt", "00:00 - 24:00"))
        got = parse_schedule(html, TZ, datetime.date(2026, 11, 1))
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0].start.date(), datetime.date(2026, 11, 4))

    def test_year_rollover_forward_and_back(self):
        html = _block("pátek 01.01. - sobota 02.01.", ("vt", "00:00 - 24:00"))
        fwd = parse_schedule(html, TZ, datetime.date(2026, 12, 30))
        self.assertEqual(fwd[0].start.date(), datetime.date(2027, 1, 1))
        back = parse_schedule(html, TZ, datetime.date(2026, 1, 1))
        self.assertEqual(back[0].start.date(), datetime.date(2026, 1, 1))

    def test_range_crossing_new_year(self):
        html = _block("středa 30.12. - pátek 01.01.", ("nt", "00:00 - 24:00"))
        got = parse_schedule(html, TZ, datetime.date(2026, 12, 29))
        self.assertEqual(got[0].start.date(), datetime.date(2026, 12, 30))
        self.assertEqual(got[-1].end.date(), datetime.date(2027, 1, 2))

    def test_malformed_blocks_raise(self):
        with self.assertRaises(HdoError):
            parse_schedule(
                '<div class="hdo-bar"><div class="blue-text">no date</div></div>',
                TZ,
                datetime.date(2026, 11, 1),
            )
        with self.assertRaises(HdoError):
            parse_schedule(_block("středa 04.11."), TZ, datetime.date(2026, 11, 1))
        with self.assertRaises(HdoError):
            parse_schedule("<div>nothing</div>", TZ, datetime.date(2026, 11, 1))

    def test_no_next_start_past_horizon(self):
        html = _block("středa 04.11.", ("nt", "00:00 - 24:00"))
        got = parse_schedule(html, TZ, datetime.date(2026, 11, 4))
        now = datetime.datetime(2026, 11, 4, 12, 0, tzinfo=TZ)
        self.assertIsNone(next_start(got, now, low=False))
        self.assertIsNone(current_interval(got, datetime.datetime(2026, 11, 6, tzinfo=TZ)))


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class _FakeSession:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return _FakeResponse(self.payload)


class DownloadTest(unittest.TestCase):
    def test_sends_command_code(self):
        session = _FakeSession({"html": _block("středa 04.11.", ("nt", "00:00 - 24:00"))})
        html = hdo.download_schedule_html("605", session)
        self.assertIn("hdo-bar", html)
        url, kwargs = session.calls[0]
        self.assertTrue(url.endswith("HdoForm:hdoMoreDaysAjax"))
        self.assertEqual(kwargs["data"]["povel"], "605")

    def test_unknown_code_is_no_data(self):
        banner = {"html": '<div class="error flash">Pro časový interval neexistují data.</div>'}
        with self.assertRaises(hdo.HdoNoDataError):
            hdo.download_schedule_html("999999", _FakeSession(banner))

    def test_bad_shape_is_hdo_error(self):
        with self.assertRaises(HdoError):
            hdo.download_schedule_html("605", _FakeSession({"nope": 1}))
        with self.assertRaises(HdoError):
            hdo.download_schedule_html("605", _FakeSession(ValueError("not json")))


def _fixture_html(name):
    with open(os.path.join(HERE, "fixtures", name), encoding="utf-8") as f:
        return json.load(f)["html"]


class DayScheduleTest(unittest.TestCase):
    """One-day endpoint (real responses for command 605)."""

    SEPT_15 = [(0, 60), (100, 286), (320, 560), (600, 781), (826, 1060), (1100, 1280), (1320, 1440)]

    def setUp(self):
        self.nt = parse_day_nt(_fixture_html("hdo_605_day_2026-09-15.json"))
        self.by_day = {datetime.date(2026, 9, 15): self.nt}

    def test_minute_precise_ranges(self):
        # Past days carry real switch minutes (04:46, 13:01, 13:46), not a 20-min grid.
        self.assertEqual(self.nt, self.SEPT_15)

    def test_nov_day_differs_by_minutes(self):
        nov = parse_day_nt(_fixture_html("hdo_605_day_2026-11-04.json"))
        self.assertEqual(nov[1], (100, 280))  # 01:40-04:40, vs 04:46 in September

    def _frac(self, h, m):
        start = datetime.datetime(2026, 9, 15, h, m)
        return nt_fraction(self.by_day, start, start + datetime.timedelta(minutes=15))

    def test_fractions_at_edges(self):
        self.assertAlmostEqual(self._frac(0, 45), 1.0)   # fully NT
        self.assertAlmostEqual(self._frac(1, 0), 0.0)    # fully VT (01:00-01:15)
        self.assertAlmostEqual(self._frac(1, 30), 5 / 15)   # NT from 01:40
        self.assertAlmostEqual(self._frac(4, 45), 1 / 15)   # NT until 04:46
        self.assertAlmostEqual(self._frac(23, 45), 1.0)  # ends at 24:00

    def test_day_totals_to_nt_minutes(self):
        total = sum(self._frac(h, m) for h in range(24) for m in (0, 15, 30, 45)) * 15
        self.assertAlmostEqual(total, sum(e - s for s, e in self.SEPT_15))

    def test_missing_day_raises_keyerror_not_silent_zero(self):
        start = datetime.datetime(2026, 9, 16, 0, 0)
        with self.assertRaises(KeyError):
            nt_fraction(self.by_day, start, start + datetime.timedelta(minutes=15))

    def test_all_high_day_has_no_nt(self):
        html = _block("středa 04.11.", ("vt", "00:00 - 24:00"))
        self.assertEqual(parse_day_nt(html), [])

    def test_no_data_banner(self):
        banner = {"html": _fixture_html("hdo_day_nodata.json")}
        with self.assertRaises(hdo.HdoNoDataError):
            hdo.download_day_html("605", datetime.date(2026, 11, 30), _FakeSession(banner))

    def test_day_request_uses_czech_date(self):
        session = _FakeSession({"html": _fixture_html("hdo_605_day_2026-09-15.json")})
        hdo.download_day_html("605", datetime.date(2026, 9, 5), session)
        self.assertEqual(session.calls[0][1]["data"]["datum"], "05.09.2026")
        self.assertTrue(session.calls[0][0].endswith("HdoForm:hdoOneDayAjax"))


class SplitTest(unittest.TestCase):
    def test_split_adds_up_to_total_per_hour(self):
        nt_ranges = {datetime.date(2026, 9, 15): DayScheduleTest.SEPT_15}
        readings = []
        t = datetime.datetime(2026, 9, 15, 0, 0)
        for i in range(96):  # one full day of 15-min readings, varying kWh
            readings.append(Reading(t, t + datetime.timedelta(minutes=15), 0.05 + 0.01 * (i % 7), 0.0))
            t += datetime.timedelta(minutes=15)
        nt, vt = to_hourly_kwh_utc_split(
            readings, TZ, lambda r: nt_fraction(nt_ranges, r.start, r.end)
        )
        total = to_hourly_kwh_utc(readings, TZ)
        self.assertEqual(set(nt), set(total))
        for hour in total:
            self.assertAlmostEqual(nt[hour] + vt[hour], total[hour])
        self.assertAlmostEqual(sum(nt.values()) + sum(vt.values()), sum(r.kwh for r in readings))
        self.assertGreater(sum(nt.values()), sum(vt.values()))  # ~83% of this day is NT

    def test_hour_fully_in_one_tariff(self):
        nt_ranges = {datetime.date(2026, 9, 15): DayScheduleTest.SEPT_15}
        hour = [Reading(datetime.datetime(2026, 9, 15, 0, m), datetime.datetime(2026, 9, 15, 0, m) + datetime.timedelta(minutes=15), 0.1, 0.0) for m in (0, 15, 30, 45)]
        nt, vt = to_hourly_kwh_utc_split(hour, TZ, lambda r: nt_fraction(nt_ranges, r.start, r.end))
        self.assertAlmostEqual(sum(nt.values()), 0.4)
        self.assertAlmostEqual(sum(vt.values()), 0.0)


if __name__ == "__main__":
    unittest.main()
