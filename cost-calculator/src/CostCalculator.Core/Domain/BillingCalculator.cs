namespace CostCalculator.Domain;

/// <summary>Reproduces the structure and the rounding of a PRE invoice (specification section 6).</summary>
public static class BillingCalculator
{
    public static Bill Calculate(decimal vtKwh, decimal ntKwh, decimal months, Breaker breaker, PriceList p)
    {
        var total = vtKwh + ntKwh;
        static decimal Item(decimal qty, decimal price) => Money.Round(qty * price);

        var supply = new BillSection("Obchod s elektřinou", new[]
        {
            new BillItem("Silová elektřina VT", vtKwh, "kWh", p.EnergyVt, Item(vtKwh, p.EnergyVt)),
            new BillItem("Silová elektřina NT", ntKwh, "kWh", p.EnergyNt, Item(ntKwh, p.EnergyNt)),
            new BillItem("Plat za odběrné místo", months, "měs.", p.MonthlyFeePerPoint, Item(months, p.MonthlyFeePerPoint)),
            new BillItem("Daň z elektřiny", total, "kWh", p.ElectricityTax, Item(total, p.ElectricityTax)),
        });

        var distribution = new BillSection("Distribuce", new[]
        {
            new BillItem("Distribuce VT", vtKwh, "kWh", p.DistributionVt, Item(vtKwh, p.DistributionVt)),
            new BillItem("Distribuce NT", ntKwh, "kWh", p.DistributionNt, Item(ntKwh, p.DistributionNt)),
            new BillItem($"Plat za příkon, jistič {breaker.Label}", months, "měs.", breaker.MonthlyFee, Item(months, breaker.MonthlyFee)),
        });

        // POZE: the law computes it two ways and the lower one applies.
        var pozeByEnergy = total * p.PozeByConsumption;
        var pozeByBreaker = months * breaker.Amps * breaker.Phases * p.PozePerAmp;
        var pozeTotal = Money.Round(Math.Min(pozeByEnergy, pozeByBreaker));

        var regulated = new BillSection("Regulované služby", new[]
        {
            new BillItem("Systémové služby", total, "kWh", p.SystemServices, Item(total, p.SystemServices)),
            new BillItem($"POZE, {breaker.Label}", months, "měs.", breaker.Amps * breaker.Phases * p.PozePerAmp, pozeTotal),
            new BillItem("Provoz nesíťové infrastruktury", months, "měs.", p.NonNetworkInfrastructure, Item(months, p.NonNetworkInfrastructure)),
        });

        return new Bill(new[] { supply, distribution, regulated }, vtKwh, ntKwh, months, p.VatRate);
    }
}
