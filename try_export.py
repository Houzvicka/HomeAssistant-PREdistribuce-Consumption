"""End-to-end smoke test for api.py: login (or a seeded cookie) + export + parse.

Usage â€” real login:
    Copy .env.example to .env, fill in PRE_USERNAME / PRE_PASSWORD / PRE_EAN
    (that file is gitignored and stays local â€” never commit it, never paste
    its contents anywhere), then:
        python try_export.py

Usage â€” skip login (e.g. while debugging a reCAPTCHA block on login itself):
    Log into predistribuce.cz in a browser, then DevTools -> Application
    (Chrome) / Storage (Firefox) -> Cookies -> www.predistribuce.cz, find the
    session cookie (not visible in a HAR export â€” those get stripped), and
    set PRE_COOKIE_NAME / PRE_COOKIE_VALUE / PRE_EAN in .env instead.

Downloads yesterday's export by default (or pass --from/--to), parses it,
and prints a summary. Values can also come from real environment variables
instead of .env â€” those always take priority if both are set.
"""
from __future__ import annotations

import argparse
import datetime
import os
import sys

# api.py/parser.py live inside the HA component but have no HA imports.
sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(__file__), "custom_components", "predistribuce_consumption"
    ),
)

from api import PortalClient, PortalError  # noqa: E402
from parser import parse, to_hourly_kwh  # noqa: E402


def load_dotenv(path: str = ".env") -> None:
    """Load KEY=VALUE lines from a local .env file into os.environ.

    Minimal, no dependency on python-dotenv. Never overrides a variable
    that's already set in the real environment.
    """
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


def parse_date(s: str) -> datetime.date:
    return datetime.datetime.strptime(s, "%d.%m.%Y").date()


def main() -> int:
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="date_from", type=parse_date, default=None)
    ap.add_argument("--to", dest="date_to", type=parse_date, default=None)
    args = ap.parse_args()

    username = os.environ.get("PRE_USERNAME")
    password = os.environ.get("PRE_PASSWORD")
    cookie_name = os.environ.get("PRE_COOKIE_NAME")
    cookie_value = os.environ.get("PRE_COOKIE_VALUE")
    ean = os.environ.get("PRE_EAN")

    if not ean:
        print("Set PRE_EAN, and either (PRE_USERNAME + PRE_PASSWORD) or "
              "(PRE_COOKIE_NAME + PRE_COOKIE_VALUE).", file=sys.stderr)
        return 1

    today = datetime.date.today()
    date_from = args.date_from or (today - datetime.timedelta(days=2))
    date_to = args.date_to or (today - datetime.timedelta(days=1))

    client = PortalClient()
    if username and password:
        try:
            client.login(username, password)
        except PortalError as e:
            print(f"Login failed: {e}", file=sys.stderr)
            return 1
    elif cookie_name and cookie_value:
        client.seed_session_cookie(cookie_name, cookie_value)
    else:
        print("Set PRE_EAN, and either (PRE_USERNAME + PRE_PASSWORD) or "
              "(PRE_COOKIE_NAME + PRE_COOKIE_VALUE).", file=sys.stderr)
        return 1

    try:
        raw = client.download_export(ean, date_from, date_to)
    except PortalError as e:
        print(f"Export failed: {e}", file=sys.stderr)
        return 1

    out_path = f"export_{date_from:%Y%m%d}_{date_to:%Y%m%d}.csv"
    with open(out_path, "wb") as f:
        f.write(raw)
    print(f"Saved raw export to {out_path} ({len(raw)} bytes)")

    readings = parse(raw)
    print(f"Parsed {len(readings)} readings")
    if readings:
        print(f"  first: {readings[0]}")
        print(f"  last:  {readings[-1]}")
        total = sum(r.kwh for r in readings)
        print(f"  total: {total:.2f} kWh")
        hourly = to_hourly_kwh(readings)
        print(f"  {len(hourly)} hourly buckets")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

