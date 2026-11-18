namespace CostCalculator.Domain;

/// <summary>Main circuit breaker rating and its monthly capacity charge (CZK/month, no VAT).</summary>
public sealed record Breaker(string Key, string Label, int Phases, int Amps, decimal MonthlyFee);

/// <summary>
/// One price list, all prices in CZK without VAT. Energy and distribution prices are per kWh
/// (the leaflet states CZK/MWh; divided by 1000).
/// </summary>
public sealed class PriceList
{
    public string Name { get; set; } = "";
    public DateOnly ValidFrom { get; set; }

    public decimal EnergyVt { get; set; }
    public decimal EnergyNt { get; set; }
    public decimal MonthlyFeePerPoint { get; set; }
    public decimal ElectricityTax { get; set; }
    public decimal DistributionVt { get; set; }
    public decimal DistributionNt { get; set; }
    public decimal SystemServices { get; set; }
    /// <summary>POZE by consumption, CZK/kWh.</summary>
    public decimal PozeByConsumption { get; set; }
    /// <summary>POZE by breaker, CZK per ampere per phase per month.</summary>
    public decimal PozePerAmp { get; set; }
    public decimal NonNetworkInfrastructure { get; set; }
    public decimal VatRate { get; set; }
    public List<Breaker> Breakers { get; set; } = new();

    public const string DefaultBreakerKey = "3x25";

    public PriceList Clone()
    {
        var copy = (PriceList)MemberwiseClone();
        copy.Breakers = Breakers.ToList();
        return copy;
    }

    public Breaker FindBreaker(string key) =>
        Breakers.FirstOrDefault(b => b.Key == key) ?? Breakers.First(b => b.Key == DefaultBreakerKey);

    /// <summary>
    /// PRE PROUD PLUS 04/2026 (supply, TOPENÍ 20) with regulated items for distribution tariff D57d.
    /// Source: the leaflet transcribed in the specification, section 8. Regulated items follow ERÚ
    /// decisions 13/2025 and 14/2025 and change from 1. 1. 2027.
    /// </summary>
    public static PriceList ProudPlus042026() => new()
    {
        Name = "PRE PROUD PLUS 04/2026, D57d (TOPENÍ 20)",
        ValidFrom = new DateOnly(2026, 4, 1),
        EnergyVt = 3.095m,
        EnergyNt = 2.795m,
        MonthlyFeePerPoint = 189.00m,
        ElectricityTax = 0.0283m,
        DistributionVt = 0.42152m,
        DistributionNt = 0.17520m,
        SystemServices = 0.16424m,
        PozeByConsumption = 0.495m,
        PozePerAmp = 0.00m,
        NonNetworkInfrastructure = 12.87m,
        VatRate = 0.21m,
        Breakers =
        {
            new("1x25", "1×25 A (a méně)", 1, 25, 154m),
            new("3x10", "3×10 A", 3, 10, 154m),
            new("3x16", "3×16 A", 3, 16, 246m),
            new("3x20", "3×20 A", 3, 20, 308m),
            new("3x25", "3×25 A", 3, 25, 385m),
            new("3x32", "3×32 A", 3, 32, 492m),
            new("3x40", "3×40 A", 3, 40, 622m),
            new("3x50", "3×50 A", 3, 50, 933m),
            new("3x63", "3×63 A", 3, 63, 1433m),
            new("3x80", "3×80 A", 3, 80, 2494m),
            new("3x100", "3×100 A", 3, 100, 4801m),
            new("3x125", "3×125 A", 3, 125, 9841m),
            new("3x160", "3×160 A", 3, 160, 20779m),
        },
    };
}
