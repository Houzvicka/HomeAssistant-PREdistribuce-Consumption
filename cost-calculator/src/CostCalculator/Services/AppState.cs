using System.Text.Json;
using CostCalculator.Domain;
using CostCalculator.Import;
using Microsoft.JSInterop;

namespace CostCalculator.Services;

public sealed record PriceField(string Label, string Unit, Func<PriceList, decimal> Get, Action<PriceList, decimal> Set);

/// <summary>Holds the loaded data and the settings; settings persist in localStorage.</summary>
public sealed class AppState
{
    private const string StorageKey = "cost-calculator-settings-v1";

    private readonly IJSRuntime _js;
    private readonly List<ParsedFile> _files = new();

    public AppState(IJSRuntime js) => _js = js;

    public PriceList DefaultPrices { get; } = PriceList.ProudPlus042026();
    public PriceList Prices { get; private set; } = PriceList.ProudPlus042026();
    public string BreakerKey { get; set; } = PriceList.DefaultBreakerKey;
    public SplitSettings Split { get; private set; } = new();

    public IReadOnlyList<ParsedFile> Files => _files;
    public Analysis? Analysis { get; private set; }
    public List<string> SplitWarnings { get; private set; } = new();
    public event Action? Changed;

    public static readonly PriceField[] PriceFields =
    {
        new("Silová elektřina VT", "Kč/kWh", p => p.EnergyVt, (p, v) => p.EnergyVt = v),
        new("Silová elektřina NT", "Kč/kWh", p => p.EnergyNt, (p, v) => p.EnergyNt = v),
        new("Plat za odběrné místo", "Kč/měsíc", p => p.MonthlyFeePerPoint, (p, v) => p.MonthlyFeePerPoint = v),
        new("Daň z elektřiny", "Kč/kWh", p => p.ElectricityTax, (p, v) => p.ElectricityTax = v),
        new("Distribuce VT", "Kč/kWh", p => p.DistributionVt, (p, v) => p.DistributionVt = v),
        new("Distribuce NT", "Kč/kWh", p => p.DistributionNt, (p, v) => p.DistributionNt = v),
        new("Systémové služby", "Kč/kWh", p => p.SystemServices, (p, v) => p.SystemServices = v),
        new("POZE podle spotřeby", "Kč/kWh", p => p.PozeByConsumption, (p, v) => p.PozeByConsumption = v),
        new("POZE podle jističe", "Kč/A/měsíc", p => p.PozePerAmp, (p, v) => p.PozePerAmp = v),
        new("Provoz nesíťové infrastruktury", "Kč/měsíc", p => p.NonNetworkInfrastructure, (p, v) => p.NonNetworkInfrastructure = v),
        new("DPH", "podíl (0,21 = 21 %)", p => p.VatRate, (p, v) => p.VatRate = v),
    };

    public Breaker Breaker => Prices.FindBreaker(BreakerKey);

    public async Task InitializeAsync()
    {
        try
        {
            var json = await _js.InvokeAsync<string?>("localStorage.getItem", StorageKey);
            if (!string.IsNullOrEmpty(json) && JsonSerializer.Deserialize<Stored>(json) is { } stored)
            {
                Prices = stored.Prices ?? Prices;
                BreakerKey = stored.BreakerKey ?? BreakerKey;
                Split = stored.Split ?? Split;
            }
        }
        catch (Exception)
        {
            // Storage unavailable or corrupt: run with the defaults.
        }
        Recalculate();
    }

    public async Task AddFilesAsync(IEnumerable<ParsedFile> files)
    {
        foreach (var f in files)
        {
            _files.RemoveAll(x => x.Name == f.Name);
            _files.Add(f);
        }
        Recalculate();
        await Task.CompletedTask;
    }

    public void ClearFiles()
    {
        _files.Clear();
        Recalculate();
    }

    public void SetPrice(PriceField field, decimal value)
    {
        field.Set(Prices, value);
        _ = SaveAndRecalculateAsync();
    }

    public void ResetPrices()
    {
        Prices = DefaultPrices.Clone();
        _ = SaveAndRecalculateAsync();
    }

    public Task SaveAndRecalculateAsync()
    {
        Recalculate();
        return SaveAsync();
    }

    public bool PricesModified =>
        JsonSerializer.Serialize(Prices) != JsonSerializer.Serialize(DefaultPrices);

    private async Task SaveAsync()
    {
        try
        {
            var json = JsonSerializer.Serialize(new Stored(Prices, BreakerKey, Split));
            await _js.InvokeVoidAsync("localStorage.setItem", StorageKey, json);
        }
        catch (Exception)
        {
            // Settings just won't persist.
        }
    }

    private void Recalculate()
    {
        SplitWarnings = TariffSplitter.Validate(Split);
        var readings = CsvParser.Merge(_files);
        Analysis = readings.Count == 0 ? null : Analyzer.Analyze(readings, Split, Prices, Breaker);
        Changed?.Invoke();
    }

    private sealed record Stored(PriceList? Prices, string? BreakerKey, SplitSettings? Split);
}
