namespace CostCalculator.Domain;

/// <summary>One 15-minute slot with its VT/NT split, for the charts.</summary>
public sealed record Slot(DateTime Start, decimal Vt, decimal Nt);

public sealed record DaySummary(DateOnly Date, decimal Vt, decimal Nt);

public sealed record MonthSummary(
    int Year,
    int Month,
    int DaysInMonth,
    decimal DaysCovered,
    decimal VtKwh,
    decimal NtKwh,
    decimal PeakKw,
    Bill SoFar,
    Bill? Projection)
{
    public bool IsComplete => Projection == null;
    public decimal TotalKwh => VtKwh + NtKwh;

    /// <summary>The headline figure: the actual cost for a complete month, else the projection.</summary>
    public Bill Headline => Projection ?? SoFar;
}

public sealed record Analysis(IReadOnlyList<MonthSummary> Months, IReadOnlyList<Slot> Slots, IReadOnlyList<DaySummary> Days);

public static class Analyzer
{
    private const int IntervalsPerDay = 96;
    // A day with 92-100 rows is a full day (spring/autumn DST change); fewer counts proportionally.
    private const int FullDayMinimumRows = 92;

    public static Analysis Analyze(IReadOnlyList<Reading> readings, SplitSettings split, PriceList prices, Breaker breaker)
    {
        var vtOf = TariffSplitter.CreateVtFunc(split);
        var slots = readings.Select(r =>
        {
            var vt = vtOf(r);
            return new Slot(r.Start, vt, r.Kwh - vt);
        }).ToList();

        var days = readings
            .Zip(slots)
            .GroupBy(x => DateOnly.FromDateTime(x.First.Start))
            .OrderBy(g => g.Key)
            .Select(g => new DaySummary(g.Key, g.Sum(x => x.Second.Vt), g.Sum(x => x.Second.Nt)))
            .ToList();

        var rowsPerDay = readings.GroupBy(r => DateOnly.FromDateTime(r.Start)).ToDictionary(g => g.Key, g => g.Count());
        var peakByMonth = readings
            .Where(r => r.Kw.HasValue)
            .GroupBy(r => (r.Start.Year, r.Start.Month))
            .ToDictionary(g => g.Key, g => g.Max(r => r.Kw!.Value));

        var months = new List<MonthSummary>();
        foreach (var g in days.GroupBy(d => (d.Date.Year, d.Date.Month)).OrderBy(g => g.Key))
        {
            var (year, month) = g.Key;
            var daysInMonth = DateTime.DaysInMonth(year, month);
            var covered = g.Sum(d => DayFraction(rowsPerDay[d.Date]));
            var vt = g.Sum(d => d.Vt);
            var nt = g.Sum(d => d.Nt);

            // Fixed fees are prorated by calendar month: each day counts as 1 / days in its month.
            var months1 = covered / daysInMonth;
            var soFar = BillingCalculator.Calculate(vt, nt, months1, breaker, prices);

            Bill? projection = null;
            if (covered < daysInMonth && covered > 0)
            {
                var scale = daysInMonth / covered;
                projection = BillingCalculator.Calculate(vt * scale, nt * scale, 1m, breaker, prices);
            }

            peakByMonth.TryGetValue((year, month), out var peak);
            months.Add(new MonthSummary(year, month, daysInMonth, covered, vt, nt, peak, soFar, projection));
        }

        return new Analysis(months, slots, days);
    }

    public static decimal DayFraction(int rows) =>
        rows >= FullDayMinimumRows ? 1m : (decimal)rows / IntervalsPerDay;
}
