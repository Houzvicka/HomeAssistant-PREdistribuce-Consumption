"""Offline tests for parser.py. Run: python -m unittest discover tests"""
import datetime
import os
import sys
import unittest

sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(__file__), "..", "custom_components", "predistribuce_consumption"
    ),
)

from parser import Reading, parse, to_hourly_kwh_utc  # noqa: E402

UTC = datetime.timezone.utc


def _last_sunday(year: int, month: int) -> datetime.date:
    d = datetime.date(year, month + 1, 1) - datetime.timedelta(days=1)
    return d - datetime.timedelta(days=(d.weekday() + 1) % 7)


class _EuCentral(datetime.tzinfo):
    """CET/CEST with EU rules (switch at 01:00 UTC), fold-aware.

    Stands in for ZoneInfo("Europe/Prague") so the test needs no tzdata
    (Windows has none and pip may be offline). Production uses ZoneInfo.
    """

    def utcoffset(self, dt):
        year = dt.year
        start = datetime.datetime.combine(
            _last_sunday(year, 3), datetime.time(1), tzinfo=UTC
        )
        end = datetime.datetime.combine(
            _last_sunday(year, 10), datetime.time(1), tzinfo=UTC
        )
        naive = dt.replace(tzinfo=None)
        cest, cet = datetime.timedelta(hours=2), datetime.timedelta(hours=1)
        # Interpret the wall time under each offset and keep the consistent one(s).
        as_cest = (naive - cest).replace(tzinfo=UTC)
        as_cet = (naive - cet).replace(tzinfo=UTC)
        cest_ok = start <= as_cest < end
        cet_ok = not (start <= as_cet < end)
        if cest_ok and cet_ok:  # ambiguous: the repeated autumn hour
            return cet if dt.fold else cest
        return cest if cest_ok else cet

    def dst(self, dt):
        return self.utcoffset(dt) - datetime.timedelta(hours=1)

    def tzname(self, dt):
        return "CEST" if self.dst(dt) else "CET"


PRAGUE = _EuCentral()


def _quarters(start: datetime.datetime, count: int, kwh: float = 0.25):
    return [
        Reading(
            start + datetime.timedelta(minutes=15 * i),
            start + datetime.timedelta(minutes=15 * (i + 1)),
            kwh,
            0.0,
        )
        for i in range(count)
    ]


class ParseTest(unittest.TestCase):
    def test_parse_czech_csv(self):
        raw = (
            "Počátek intervalu;Konec intervalu;X - Činná - spotřeba [kWh];X - Činný - výkon [kW];\r\n"
            "01.08.2026 00:00;01.08.2026 00:15;0,030;0,120;\r\n"
        ).encode("iso-8859-2")
        (r,) = parse(raw)
        self.assertEqual(r.start, datetime.datetime(2026, 8, 1, 0, 0))
        self.assertAlmostEqual(r.kwh, 0.03)
        self.assertAlmostEqual(r.kw, 0.12)


class HourlyUtcTest(unittest.TestCase):
    def test_summer_day_is_utc_plus_two(self):
        readings = _quarters(datetime.datetime(2026, 8, 1, 0, 0), 8)
        hourly = to_hourly_kwh_utc(readings, PRAGUE)
        self.assertEqual(
            sorted(hourly),
            [
                datetime.datetime(2026, 7, 31, 22, tzinfo=UTC),
                datetime.datetime(2026, 7, 31, 23, tzinfo=UTC),
            ],
        )
        self.assertAlmostEqual(sum(hourly.values()), 2.0)

    def test_autumn_repeated_hour_is_not_merged(self):
        # 2026-10-25: 03:00 CEST -> 02:00 CET, so 02:00-03:00 occurs twice.
        # 01:00 .. 04:00 wall time = 5 real hours.
        readings = (
            _quarters(datetime.datetime(2026, 10, 25, 1, 0), 8)  # 01:00-03:00 first pass
            + _quarters(datetime.datetime(2026, 10, 25, 2, 0), 8)  # 02:00-04:00 second pass
        )
        hourly = to_hourly_kwh_utc(readings, PRAGUE)
        self.assertEqual(len(hourly), 4)
        self.assertEqual(
            sorted(hourly),
            [
                datetime.datetime(2026, 10, 24, 23, tzinfo=UTC),
                datetime.datetime(2026, 10, 25, 0, tzinfo=UTC),
                datetime.datetime(2026, 10, 25, 1, tzinfo=UTC),
                datetime.datetime(2026, 10, 25, 2, tzinfo=UTC),
            ],
        )
        for v in hourly.values():
            self.assertAlmostEqual(v, 1.0)


if __name__ == "__main__":
    unittest.main()
