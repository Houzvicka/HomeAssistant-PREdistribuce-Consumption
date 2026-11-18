# Progress log

State as of **2026-11-04**. No secrets, EANs or addresses in this file.
Nothing is committed to git yet (the repo has no commits).

## Done and working

- **Consumption import** (portal login -> CSV export -> hourly external
  statistics). Deployed to the user's Home Assistant (HA OS, reachable on the
  LAN) on 2026-11-02, added through the UI, and the data shows in the
  Energy dashboard (Electricity grid).
- **HDO schedule entities** (deployed, not yet enabled — no code entered):
  `binary_sensor` "Low tariff", sensors "Next low/high tariff start", own
  device, 6-hourly refresh, entities flip at the exact switch time.
  Source: public PRE page, no login (`hdo.py` docstring has the endpoints).

## Written and tested locally, NOT deployed

NT/VT split of consumption, so the Energy dashboard can use two prices:

- With an HDO code set, also writes statistics `predistribuce_consumption:<ean>_nt`
  and `..._vt`; each 15-min reading is split by overlap with low tariff.
- Uses PRE's **actual per-day HDO record** (`hdoOneDayAjax`, `datum=DD.MM.YYYY`):
  works for past dates back to at least 2021 with minute-precise times, and
  ~2 weeks ahead. One request per day, past days cached.
- New option "Days of history to split by tariff" (default 120).
- Files changed vs the deployed copy: `config_flow.py`, `const.py`,
  `coordinator.py`, `hdo.py`, `parser.py`, `statistics.py`, `strings.json`,
  `translations/en.json`.
- 27 offline tests pass (`python -m unittest discover tests`). Real-data dry
  run (outside HA, code 605, 107 days): NT+VT equals the portal total for
  every hour; 83.6 % of kWh in NT, 83.4 % of clock time (matches ~20 h NT/day).
- **Never run inside Home Assistant** — only the parsing/splitting logic is
  tested. Expect possible first-run issues in entity/statistics/options-flow
  setup (`OptionsFlowWithReload` needs HA 2025.8+; README says 2025.10+).

## Key findings (so they are not re-discovered)

- Tariff is **D57d** (heat pump, ~20 h NT/day), TDD 7, breaker 3x25 A, supplier
  product PRE PROUD PLUS. Meter is a **ZPA AM375** — a "new type" meter with
  **no HDO receiver and no code sticker**; switching follows a TOU table, and
  the **TOU ID is shown on the meter display**.
- PRE's AMM TOU table (public xlsx, linked from the HDO page) has only two
  D57D entries: **ID 1052 = command 573**, **ID 1053 = command 605**. The
  command is what the integration's "HDO command code" field takes. The
  user thinks it is 1053 (-> **605**) but has **not confirmed it** on the display.
- The TOU table agrees with the live HDO page for the same codes (TOU is on a
  15-min grid, the forecast on a 20-min grid).
- The portal itself does not expose the HDO code or tariff (only measurement
  type C, category 1, NN, breaker). The consumption profile has no NT/VT
  column, and consumption shows no signature of the tariff windows, so the
  code cannot be inferred from consumption data.
- The consumption CSV has only start, end, kWh, kW. Energy dashboard allows
  one price per consumption source -> two sources (`_nt`, `_vt`) is the way.
- Earlier wrong turns, corrected: advice to read a code off a receiver (does
  not apply to AM375); "no HDO history on the website" (it has years of it).

## Open items

1. **Confirm the TOU ID** on the meter display (1052 -> 573, 1053 -> 605), or
   send invoice NT/VT kWh for a period to test 573 vs 605 against it. A wrong
   code is not fixed retroactively for split history (only the last few days
   are rewritten), so settle this before the first split run.
2. **Deploy the NT/VT split** — needs SSH access to the HA host again (the
   user must enable it and give consent; the temporary key and password
   helper were deleted from the scratchpad). Then restart HA, enter the code
   under Configure, check the log for `Imported NT/VT split`.
3. In Energy -> Electricity grid, swap the single source for `_nt` and `_vt`,
   each with its full per-kWh price (supplier + distribution + taxes; user's
   figures from the invoice needed).
4. Verify the autumn DST hour (2026-10-25) in the imported data.
5. Security cleanup on the HA side: remove `claude-deploy-temp` from the SSH
   add-on `authorized_keys`; disable/rotate the root password (it was shared
   in chat).
6. Possible polish, not built: dropdown of codes + schedule preview in the
   config flow; accept a TOU ID (e.g. 1053) in addition to a command code;
   per-device consumption via the Energy dashboard "Individual devices"
   (needs devices with kWh sensors — no code change).
7. Make the first git commit when the user asks.

## How to resume

- Local checks: `python -m unittest discover tests`; live fetch smoke test
  `python try_export.py` (needs `.env`, never commit it).
- Deploying: copy `custom_components/predistribuce_consumption/` (no
  `__pycache__`) to `/config/custom_components/` on the HA host (`/config` is a
  symlink to `/homeassistant` on HA OS), then restart HA.
