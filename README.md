# HomeAssistant-PREdistribuce-Consumption

Custom Home Assistant integration that periodically downloads electricity
consumption data from the **PRE distribuce** customer portal ("Profily
spotřeby" export) and feeds it into Home Assistant's Energy dashboard as
long-term statistics. Optionally it also exposes the **HDO** (low/high
tariff) schedule — see [HDO (low/high tariff)](#hdo-lowhigh-tariff).

> **Status (2026-10-31):** the fetch pipeline is proven against the live
> account (login, export, parsing), and the HDO download/parse was run
> against the live public page. The HA integration in
> `custom_components/predistribuce_consumption/` is written but has
> **never run inside Home Assistant** — only `parser.py` and `hdo.py` have
> offline tests. Next step: deploy it to a real HA instance, see
> [Deploying to Home Assistant](#deploying-to-home-assistant).

## Goal

- Log in to the PRE distribuce customer portal using stored credentials.
- Download the consumption export (CSV, 15-minute interval readings) for a
  given meter (EAN) and date range.
- Parse the export into timestamped kWh readings.
- Push the readings into HA as **external statistics**, so they appear
  correctly in Settings → Dashboards → Energy, including backfilled
  historical days.
- Run on a daily schedule — confirmed below to be not just sufficient but
  the ceiling, since the portal itself has a one-day lag.

## What's built so far

`api.py` and `parser.py` (working, tested against the live portal) now live
inside the component folder; they have no HA imports, so `try_export.py`
still uses them standalone.

| File | Purpose |
|---|---|
| `custom_components/predistribuce_consumption/api.py` | `PortalClient` — `login()`, `download_export()`. Endpoint details, the auth cookie situation, and known fragilities (reCAPTCHA) are in its module docstring. |
| `.../parser.py` | `parse()` turns raw CSV bytes into `Reading` objects; `to_hourly_kwh()` / `to_hourly_kwh_utc()` sum 15-min readings into hour buckets (the latter tz-aware UTC and DST-fold-safe, used by the integration). |
| `.../statistics.py` | Writes hourly kWh as cumulative external statistics, seeding `sum` from the hour before the first one written. |
| `.../coordinator.py` | Daily: backfill on first run, otherwise re-fetch the last 3 days; login → export → parse → statistics. |
| `.../config_flow.py`, `sensor.py` | UI setup validated by a real login (plus reauth), an options flow for the HDO code, and a diagnostic "Last imported day" sensor. |
| `.../hdo.py` | HDO: downloads the public schedule for a command code and parses it into merged `Interval`s. No HA imports. |
| `.../hdo_coordinator.py`, `entity.py`, `binary_sensor.py` | HDO coordinator (6-hourly), a base entity that re-evaluates exactly at tariff switches, and the "Low tariff" binary sensor. The HDO "next start" sensors live in `sensor.py`. |
| `try_export.py` | End-to-end smoke test without HA. See [Local testing](#local-testing). |
| `tests/test_parser.py`, `tests/test_hdo.py` | Offline tests (`python -m unittest discover tests`). `tests/fixtures/hdo_605.json` is a captured live HDO response. |
| `.env.example` | Template for local credentials — copy to `.env`. `.env` is gitignored. |

## Deploying to Home Assistant

Needs HA Core **2025.10 or newer** (uses `StatisticMeanType` / `unit_class`).

1. Copy the folder `custom_components/predistribuce_consumption` into
   `/config/custom_components/` on the HA host (Samba share, SSH, or the
   File editor add-on). The result must be
   `/config/custom_components/predistribuce_consumption/manifest.json`.
2. Restart HA (Settings → System → Restart).
3. Settings → Devices & services → Add integration → "PREdistribuce
   Consumption". Enter portal username, password, EAN, days of history.
4. First import runs at once. Check Settings → System → Logs (filter
   `predistribuce`) for `Imported N hourly statistics`; the
   "Last imported day" sensor should show yesterday.
5. Developer tools → Statistics should list
   `predistribuce_consumption:<ean>`. Add it under Settings → Dashboards →
   Energy → Electricity grid → Add consumption.
6. To force a re-fetch: Developer tools → Actions →
   `homeassistant.update_entity` on the "Last imported day" sensor. Enable
   debug logs with `logger: logs: custom_components.predistribuce_consumption: debug`.

Watch for on the first real run: the sensor/entity setup (never run
against real HA), `unit_class`/`mean_type` being accepted by your Core
version, and the autumn DST hour (2026-10-25) — how the portal exports the
repeated 02:00–03:00 hour is unverified.

## HDO (low/high tariff)

Optional. Enter the **HDO command code** (receiver command, *povel*, e.g.
`605` — printed on the meter or in the contract) in the setup form, or add /
change / clear it later via Settings → Devices & services → PREdistribuce
Consumption → Configure. The code is checked against the portal on submit.
Without a code, no HDO entities are created and nothing is fetched.

Unlike consumption this needs **no login**: it uses the same public page as
PRE's "Stav HDO" web form (`api` details in the `hdo.py` docstring), refreshed
every 6 hours. Entities (under a "PREdistribuce HDO <code>" service device):

| Entity | What |
|---|---|
| `binary_sensor` "Low tariff" | On during low tariff (NT). Attributes: `current_ends`, and `schedule` (the next 48 h of intervals as `start` / `end` / `tariff`). |
| `sensor` "Next low tariff start" | Timestamp of the next NT period. |
| `sensor` "Next high tariff start" | Timestamp of the next VT period. |

Entities flip at the exact switch time on their own timers, not on the
6-hour poll. The schedule covers about two weeks ahead, so if a refresh
fails the entities keep working from the last good copy; a failing HDO
fetch never stops the consumption import. Example automation condition:
`{{ is_state('binary_sensor.<name>_low_tariff', 'on') }}`.

### NT/VT split of consumption (for two prices in the Energy dashboard)

HA's Energy dashboard takes one price per consumption source, and the portal
export has no tariff column, so with an HDO code set the integration also
writes two extra statistics next to the unchanged total:
`predistribuce_consumption:<ean>_nt` and `..._vt`. Each 15-minute reading is
split by how much of it overlapped low tariff, using PRE's **actual per-day
HDO record** — the one-day endpoint (`hdoOneDayAjax`) answers for past dates
back to at least 2021 with minute-precise switch times, so history splits
properly and holidays need no special handling. NT + VT equals the portal
total for every hour (unit-tested, and checked on a real 107-day run).

In Energy → Electricity grid, replace the single source by two: the `_nt`
statistic with your NT price and the `_vt` one with your VT price (each price
must be the full per-kWh figure: supplier + distribution + taxes).

- First run after setting the code fetches one schedule per day of history
  (Configure → "Days of history to split by tariff", default 120, ~50 s for
  107 days); later runs only the last few days (past days are cached).
- If the schedule fetch fails, that run still imports the total and skips the
  split; it catches up on the next run.
- Changing the code later does **not** recompute existing split history
  (it is only rewritten for the last few days). Pick the right code first.
- Meters without an HDO receiver (e.g. ZPA AM375) use a TOU ID shown on the
  meter display instead of a code printed on a receiver. For D57d the AMM
  TOU table has just two entries: ID 1052 = command 573, ID 1053 = command
  605 — enter the command.

Caveats: PRE states the plan is informational and may change at any time;
a command code's schedule can differ from what your own meter actually does
if the meter uses a TOU table instead. DST-change days (the portal draws a
24 h bar) are not handled specially. Like the rest of the HA side, this is
unverified inside a real Home Assistant.

## Local testing

No HA instance needed to test the fetch side:

1. Copy `.env.example` to `.env`.
2. Fill in `PRE_USERNAME`, `PRE_PASSWORD`, `PRE_EAN` — real values, in that
   file only. `.env` is gitignored; never commit it, never paste its
   contents anywhere.
3. `python try_export.py` (optionally `--from DD.MM.YYYY --to DD.MM.YYYY`,
   defaults to yesterday only). It logs in, downloads, parses, saves the
   raw CSV as `export_<from>_<to>.csv` (also gitignored via `*.csv`), and
   prints a summary — reading count, first/last timestamp, total kWh,
   hourly bucket count.

If `login()` ever gets blocked (see the reCAPTCHA caveat in `api.py`), skip
it by setting `PRE_COOKIE_NAME=PHPSESSID` and `PRE_COOKIE_VALUE=<value from
a live browser session>` in `.env` instead of the username/password pair —
`try_export.py` picks whichever is set.

## Confirmed portal behavior

Everything below was reverse-engineered from two HAR captures
(2026-09-08) and then **verified against the live account** (2026-09-15),
not just inferred from traffic analysis:

- **Export endpoint**: `POST /cs/muj-ucet/profily-spotreby/`, form-encoded
  body (`eans_to_export[]`, `cinna[]`, `induktivni[]`, `kapacitni[]`,
  `cumulative2=on`, `export_CSV=Exportovat CSV`, `_form_=exportCSVForm`,
  `date_from`/`date_to` as `DD.MM.YYYY`). Response is `Content-Disposition:
  attachment; filename="Profily_spotreby_DD.MM.YYYY.csv"` — semicolon-
  delimited, ISO-8859-2, Czech decimal commas, 15-minute intervals. Same
  shape as a manual export from the portal UI.
- **Login endpoint**: `POST /cs/muj-ucet/prihlaseni-uzivatele/`, form
  fields `alias` (username/email), `password`, `login=Přihlásit`,
  `recaptcha_response` (empty in the captured login), `_form_=PREdi\ClientPortal\LogIn\LogIn::createLogInForm`,
  `redirect=`. No CSRF field. Success is a 302 to `/cs/muj-ucet/` (via an
  http→https double-hop, both followed transparently by `requests`).
- **Auth**: the `PHPSESSID` cookie (confirmed via DevTools → Application →
  Cookies — both HAR exports strip all cookie data, so this had to be
  checked directly rather than read off traffic). Two F5 BIG-IP WAF
  persistence cookies (`TS0117fb81`, `TSe...`) ride along too. All three
  show Expires/Max-Age = "Session" — no explicit lifetime, just whatever
  PHP's server-side idle timeout is (unmeasured, and irrelevant here: a
  `requests.Session()` just holds them for the life of the process, and
  `login()` runs fresh at the start of every run rather than persisting a
  session across runs).
- **CAPTCHA risk, partially resolved**: the login form has a
  `recaptcha_response` field, empty in the captured (successful) login —
  likely an invisible/score-based reCAPTCHA v3 that isn't always enforced.
  A plain `requests` client can't solve a real challenge if one ever shows
  up. **If `login()` starts failing where it used to work, suspect this
  first** — the fix would be a headless-browser client (Playwright)
  instead of raw HTTP.
- **One-day lag, confirmed empirically**: a range including *today*
  returns a real attachment, but every row for today is zero-filled
  (`kwh=0.0`, `kw=0.0`) — a placeholder shape for a day still in progress,
  not missing data. Yesterday and earlier have real values.
  **`download_export()` callers must never request today; always cap
  `date_to` at yesterday.** This also settles how often to poll: there's
  no lag shorter than a day to poll faster for, so once-daily is the
  ceiling, not just a reasonable default.
- **History depth**: on this account, data starts **2026-07-20** — a hard
  cutoff. The day before and earlier return a clean `NoDataError`
  (detected from the portal's own `Pro tuto sestavu nejsou dostupná žádná
  data.` message), not an error page or a crash. A backfill request can
  safely ask for a large range (400+ days tested) without pre-checking the
  boundary — the portal just silently returns only the days that have
  data. Whether 2026-07-20 is this meter's activation date or a retention
  policy wasn't determined, and doesn't matter for this project either way.

Still open:

- [ ] Whether the portal's Terms of Service restrict automated/scripted
      access — worth a quick check before relying on this long-term.

## Why external statistics, not a normal sensor

Portal exports are historical and arrive with a delay — sometimes with a
gap-fill or correction for previous days. A normal `sensor` entity only
represents "now," and HA's recorder assumes monotonically increasing state
changes in real time. Retroactive/backdated values need to go through
`homeassistant.components.recorder.statistics.async_add_external_statistics`,
which is exactly how integrations like Octopus Energy and the Spanish
`edata` (Datadis) integration handle utility-supplied historical data.

**Note (checked Sep 2026):** as of HA Core 2025.11, the `StatisticMetaData`
passed to `async_add_external_statistics` must set `unit_class` explicitly
(it used to default, that default is gone) — see the
[recorder statistics API changes](https://developers.home-assistant.io/blog/2025/10/16/recorder-statistics-api-changes/)
dev-docs post. Worth checking against whatever HA Core version is actually
running before writing `statistics.py`, since this API keeps moving.

## Architecture

```
custom_components/predistribuce_consumption/
├── __init__.py          # integration setup, creates the coordinator
├── manifest.json        # domain, requirements, version
├── config_flow.py        # UI setup: portal username/password, EAN/meter id
├── coordinator.py        # DataUpdateCoordinator: login -> download -> parse
├── api.py                 # PortalClient: session/auth + export download
├── parser.py              # turn CSV rows into (timestamp, kWh) list
├── statistics.py          # push parsed rows into recorder external stats
├── const.py                # DOMAIN, default scan interval, statistic_id
└── strings.json / translations/  # config flow UI text
```

### Flow

1. `api.PortalClient.login()` — authenticates against the portal, holds
   the session cookie.
2. `api.PortalClient.download_export(ean, date_from, date_to)` — fetches
   the raw CSV bytes for the requested range (`date_to` capped at
   yesterday — see [Confirmed portal behavior](#confirmed-portal-behavior)).
3. `parser.parse(raw_bytes)` → `list[Reading]`; `parser.to_hourly_kwh()`
   sums to hour-aligned buckets.
4. `statistics.insert(rows)` — calls `async_add_external_statistics` with
   `statistic_id="predistribuce_consumption:<ean>"`, `source="predistribuce_consumption"`,
   summing to cumulative `sum` and per-period `state`/`mean` as required by
   the recorder schema (remember `unit_class`, see note above).
5. `coordinator.py` ties 1–4 together, runs once daily, and re-fetches the
   last few days each run to absorb any late corrections the portal makes
   (catch `api.NoDataError` and skip rather than treat it as a failure —
   it's the expected response for a day with no data yet).

## Configuration (planned)

Set up entirely through the HA UI (`config_flow.py`), asking for:

- Portal username / password (the portal has no session-token alternative
  — confirmed, it's alias+password only)
- EAN / meter identifier
- Which day of history to backfill on first setup (e.g. last 30 days, or
  "everything" — safe to just ask for a large range, see
  [Confirmed portal behavior](#confirmed-portal-behavior))

The config flow should call `PortalClient.login()` as a validation step on
submit, so bad credentials surface immediately as an inline form error
instead of silently failing on the first scheduled coordinator run.

No YAML configuration is planned — config entries only.

## Maintenance notes

- This integration scrapes/automates a customer portal with no official
  API contract. A layout or login-flow change on PRE's side will break it;
  budget for occasional fixes.
- Keep credentials only in the HA config entry, never hardcoded. **Not
  encrypted at rest, though** — HA stores config entry data (including
  passwords) as plain JSON in `.storage/core.config_entries`. This is a
  known, still-open limitation across HA core, not something specific to
  this integration — see the
  ["WTH 2025" community thread](https://community.home-assistant.io/t/wth-2025-a-secret-is-secret-why-are-passwords-in-plain-text-in-the-config-entries-file/809838)
  and [home-assistant/core#27351](https://github.com/home-assistant/home-assistant/issues/27351).
  The only mitigations are OS-level: normal file permissions on the HA
  config directory, full-disk encryption if that's a concern, and an
  encryption passphrase on HA backups (which do support that).

## References / prior art

- [bottlecapdave/homeassistant-octopusenergy](https://github.com/bottlecapdave/homeassistant-octopusenergy) —
  meter consumption + cost tracking for Octopus Energy UK.
- [uvejota/homeassistant-edata](https://github.com/uvejota/homeassistant-edata) —
  pulls consumption from the Spanish Datadis portal, same external-statistics
  approach.
- [klausj1/homeassistant-statistics](https://github.com/klausj1/homeassistant-statistics) —
  the file-import integration used for the manual proof of concept below.
- [slesinger/HomeAssistant-PREdistribuce](https://github.com/slesinger/HomeAssistant-PREdistribuce) —
  existing PRE integration, only for the HDO (low/high tariff schedule)
  page, not consumption export data. This project's HDO support covers the
  same ground but is a separate implementation (it reads the page's AJAX
  endpoint rather than scraping the full page).

## Proof of concept (destination side)

Before any of the above, manually validated that a PREdistribuce export
can drive the Energy dashboard at all, using a real portal export
(`Profily_spotreby_03.09.2026.csv`, meter EAN <your EAN>, August
2026, 15-minute intervals):

1. Aggregated the 15-minute kWh values to hourly (`Profily_spotreby_03.09.2026_HA_import.csv`).
2. Imported them via the `homeassistant-statistics` custom integration's
   `import_statistics.import_from_file` service (see reference above).
3. Confirmed the data appears correctly as a source in the Energy dashboard.

This project replaces that manual export + service-call step with an
automated pipeline that calls the recorder's statistics API directly from
Python instead of going through that helper integration.
