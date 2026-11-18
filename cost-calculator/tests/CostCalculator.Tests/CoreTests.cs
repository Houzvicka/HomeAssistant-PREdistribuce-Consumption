using System.Text;
using CostCalculator.Domain;
using CostCalculator.Import;

namespace CostCalculator.Tests;

public class BillingTests
{
    private static Bill InvoiceBill() =>
        BillingCalculator.Calculate(127m, 661m, 2.43m, PriceList.ProudPlus042026().FindBreaker("3x25"), PriceList.ProudPlus042026());

    private static decimal Item(Bill b, string label) => b.Sections.SelectMany(s => s.Items).Single(i => i.Label.StartsWith(label)).Total;

    // Reference invoice 191148031 (specification section 9).
    [Theory]
    [InlineData("Silová elektřina VT", 393.07)]
    [InlineData("Silová elektřina NT", 1847.50)]
    [InlineData("Plat za odběrné místo", 459.27)]
    [InlineData("Daň z elektřiny", 22.30)]
    [InlineData("Distribuce VT", 53.53)]
    [InlineData("Distribuce NT", 115.81)]
    [InlineData("Plat za příkon", 935.55)]
    [InlineData("Systémové služby", 129.42)]
    [InlineData("POZE", 0.00)]
    [InlineData("Provoz nesíťové infrastruktury", 31.27)]
    public void Invoice_items_match(string label, double expected) =>
        Assert.Equal((decimal)expected, Item(InvoiceBill(), label));

    [Fact]
    public void Invoice_subtotals_and_total_match()
    {
        var bill = InvoiceBill();
        Assert.Equal(2722.14m, bill.Sections[0].Subtotal);
        Assert.Equal(1104.89m, bill.Sections[1].Subtotal);
        Assert.Equal(160.69m, bill.Sections[2].Subtotal); // the invoice prints 1 265,58 here: distribution + regulated
        Assert.Equal(3987.72m, bill.TotalWithoutVat);
    }

    [Fact]
    public void Vat_is_straight_21_percent_of_total()
    {
        var bill = InvoiceBill();
        Assert.Equal(837.42m, bill.Vat); // PRE's invoice shows 837,41 (computed from the advances base)
        Assert.Equal(4825.14m, bill.TotalWithVat);
    }

    [Fact]
    public void Poze_takes_the_lower_of_the_two_variants()
    {
        // 0.00 CZK/A/month makes the breaker variant 0, which is always lower.
        var bill = BillingCalculator.Calculate(100m, 100m, 1m, PriceList.ProudPlus042026().FindBreaker("3x25"), PriceList.ProudPlus042026());
        Assert.Equal(0m, Item(bill, "POZE"));
    }
}

public class ParserTests
{
    private const string Header = "Počátek intervalu;Konec intervalu;859182400000000001 - Činná - spotřeba [kWh];859182400000000001 - Činný - výkon [kW];\r\n";

    [Fact]
    public void Parses_rows_and_ean()
    {
        var text = Header + "13.09.2026 00:00;13.09.2026 00:15;0,050;0,200;\r\n13.09.2026 00:15;13.09.2026 00:30;0,050;0,200;\r\n";
        var file = CsvParser.ParseText("x.csv", text);
        Assert.Equal("859182400000000001", file.Ean);
        Assert.Equal(2, file.Readings.Count);
        Assert.Equal(0.05m, file.Readings[0].Kwh);
        Assert.Equal(0.2m, file.Readings[0].Kw);
    }

    [Fact]
    public void Falls_back_to_windows_1250()
    {
        Encoding.RegisterProvider(CodePagesEncodingProvider.Instance);
        var bytes = Encoding.GetEncoding(1250).GetBytes(Header + "13.09.2026 00:00;13.09.2026 00:15;0,050;0,200;\r\n");
        var text = CsvParser.Decode(bytes);
        Assert.Contains("Počátek", text);
    }

    [Fact]
    public void Repeated_hour_on_autumn_change_is_kept_but_merged_files_dedupe()
    {
        var rows = "25.10.2026 02:00;25.10.2026 02:15;0,100;0,400;\r\n25.10.2026 02:00;25.10.2026 02:15;0,200;0,800;\r\n";
        var a = CsvParser.ParseText("a", Header + rows);
        var b = CsvParser.ParseText("b", Header + rows);
        Assert.Equal(2, a.Readings.Count);
        Assert.Equal(2, CsvParser.Merge(new[] { a, b }).Count);
    }

    [Fact]
    public void Sample_has_192_rows()
    {
        var s = SampleData.Create();
        Assert.Equal(192, s.Readings.Count);
    }
}

public class SplitAndMonthTests
{
    [Fact]
    public void Hdo_windows_split_weekday_and_weekend()
    {
        var s = new SplitSettings { Mode = SplitMode.HdoSchedule, WeekdayWindows = "07:00-08:00, 11:00-12:00", WeekendWindows = "22:00-02:00" };
        var vt = TariffSplitter.CreateVtFunc(s);
        Assert.Equal(1m, vt(new Reading(new DateTime(2026, 9, 14, 7, 15, 0), new DateTime(2026, 9, 14, 7, 30, 0), 1m, null))); // Monday
        Assert.Equal(0m, vt(new Reading(new DateTime(2026, 9, 14, 9, 0, 0), new DateTime(2026, 9, 14, 9, 15, 0), 1m, null)));
        Assert.Equal(1m, vt(new Reading(new DateTime(2026, 9, 13, 23, 0, 0), new DateTime(2026, 9, 13, 23, 15, 0), 1m, null))); // Sunday
        Assert.Equal(1m, vt(new Reading(new DateTime(2026, 9, 13, 1, 0, 0), new DateTime(2026, 9, 13, 1, 15, 0), 1m, null))); // crosses midnight
    }

    [Fact]
    public void Validate_warns_when_windows_are_not_4_hours()
    {
        var s = new SplitSettings { Mode = SplitMode.HdoSchedule, WeekdayWindows = "07:00-08:00", WeekendWindows = "07:00-09:00, 11:00-13:00" };
        var warnings = TariffSplitter.Validate(s);
        Assert.Single(warnings);
        Assert.Contains("pracovní dny", warnings[0]);
    }

    [Fact]
    public void Fixed_share_splits_proportionally()
    {
        var s = new SplitSettings { Mode = SplitMode.FixedShare, VtSharePercent = 25m };
        Assert.Equal(0.25m, TariffSplitter.CreateVtFunc(s)(new Reading(DateTime.Today, DateTime.Today, 1m, null)));
    }

    [Fact]
    public void Sample_month_is_incomplete_and_projected()
    {
        var prices = PriceList.ProudPlus042026();
        var analysis = Analyzer.Analyze(SampleData.Create().Readings, new SplitSettings(), prices, prices.FindBreaker("3x25"));
        var month = Assert.Single(analysis.Months);
        Assert.Equal(2m, month.DaysCovered);
        Assert.Equal(30, month.DaysInMonth);
        Assert.NotNull(month.Projection);
        Assert.Equal(2m / 30m, month.SoFar.Months);
        Assert.Equal(1m, month.Projection!.Months);
        // NT+VT equals the total
        Assert.Equal(month.TotalKwh, analysis.Slots.Sum(s => s.Vt + s.Nt));
    }

    [Fact]
    public void Invoice_period_month_fraction_is_2_43()
    {
        var fraction = 13m / 30m + 31m / 31m + 31m / 31m;
        Assert.Equal(2.43m, Math.Round(fraction, 2));
    }
}
