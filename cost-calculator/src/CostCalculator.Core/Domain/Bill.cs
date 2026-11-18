namespace CostCalculator.Domain;

public sealed record BillItem(string Label, decimal Quantity, string Unit, decimal UnitPrice, decimal Total);

public sealed record BillSection(string Title, IReadOnlyList<BillItem> Items)
{
    public decimal Subtotal => Items.Sum(i => i.Total);
}

/// <summary>An invoice-shaped result. Every item is rounded to 0.01 CZK.</summary>
public sealed record Bill(
    IReadOnlyList<BillSection> Sections,
    decimal VtKwh,
    decimal NtKwh,
    decimal Months,
    decimal VatRate)
{
    public decimal TotalWithoutVat => Sections.Sum(s => s.Subtotal);

    /// <summary>Straight VAT on the total, rounded to 0.01. PRE's invoice may differ by 0.01 CZK.</summary>
    public decimal Vat => Money.Round(TotalWithoutVat * VatRate);

    public decimal TotalWithVat => TotalWithoutVat + Vat;
    public decimal TotalKwh => VtKwh + NtKwh;
    public decimal AveragePriceWithVat => TotalKwh > 0 ? TotalWithVat / TotalKwh : 0m;
}

public static class Money
{
    public static decimal Round(decimal value) => Math.Round(value, 2, MidpointRounding.AwayFromZero);
}
