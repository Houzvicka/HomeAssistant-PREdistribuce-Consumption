# Kalkulačka ceny elektřiny (D57d)

Blazor WebAssembly app (.NET 8, no backend). It takes the 15-minute CSV export from the
PREdistribuce portal and computes the monthly electricity cost the way PRE's invoice does:
item by item, with the monthly fixed fees and 21 % VAT. See the specification in
`electricity-cost-calculator-spec.md`.

## Run and test

```
dotnet run --project src/CostCalculator        # http://localhost:5000
dotnet test tests/CostCalculator.Tests         # includes the invoice reproduction test
dotnet publish src/CostCalculator -c Release -o out   # static files in out/wwwroot
```

Host `out/wwwroot` on any static host (GitHub Pages needs a `<base href>` change in `index.html`).

## What it does

- Loads one or more CSV files (UTF-8 or Windows-1250), merges and de-duplicates them, keeps the
  repeated hour of the autumn DST change.
- Splits consumption into VT/NT: by HDO windows (weekday and weekend, midnight crossing allowed,
  warns when they do not total 4 h) or by a fixed VT share (default 16.1 %).
- Prices every calendar month: supply, distribution, regulated items, fixed monthly fees prorated
  by calendar day, VAT. For an incomplete month it shows the cost so far and a full-month projection.
- Price list PRE PROUD PLUS 04/2026 for D57d is built in; every price can be overridden and reset.
  Settings live in the browser's `localStorage` only.

## Not built (spec section 4 and open items)

- Loading directly from the portal. The portal needs a login and almost certainly sends no CORS
  headers, so the CSV drop is the way for now.
- Single-phase breakers above 1×25 A and three-phase above 3×160 A (per-ampere rows 19 and 20).
- Dated regulated prices: change them by hand from 1. 1. 2027.

## Checked

Calculate(VT 127, NT 661, 2.43 months, 3×25 A) gives the invoice items exactly and
3 987,72 Kč without VAT. Straight 21 % VAT gives 837,42 Kč; the invoice shows 837,41 Kč.
