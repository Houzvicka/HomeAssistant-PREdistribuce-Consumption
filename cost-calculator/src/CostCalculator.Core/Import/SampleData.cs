using CostCalculator.Domain;

namespace CostCalculator.Import;

/// <summary>Built-in sample: 13.-14. 9. 2026, 192 intervals (specification section 10). Values in Wh.</summary>
public static class SampleData
{
    public const string Name = "ukázka export_20260913_20260914.csv";

    private static readonly int[] Wh =
    {
        50,50,40,50,50,50,50,40,50,50,40,50,50,50,50,40,50,50,50,40,50,50,50,50,
        40,50,50,50,40,50,50,40,50,50,40,150,50,60,50,50,100,80,100,130,120,120,390,250,
        180,180,170,160,170,160,410,200,320,180,140,120,130,420,530,130,130,110,100,110,110,420,260,110,
        100,90,90,90,80,480,200,360,80,130,100,650,220,110,120,120,100,110,110,110,90,110,60,60,
        70,60,50,50,60,50,40,60,50,40,50,50,50,50,50,40,60,50,40,50,50,50,50,50,
        40,50,50,60,50,50,50,120,430,610,590,650,590,580,560,340,60,40,50,50,50,50,50,50,
        50,50,40,50,50,50,50,50,50,50,70,60,70,60,80,100,100,130,180,180,180,170,160,180,
        160,150,150,150,150,150,140,150,140,110,80,80,80,80,80,70,70,80,80,70,80,70,500,620,
    };

    public static ParsedFile Create()
    {
        var start = new DateTime(2026, 9, 13, 0, 0, 0);
        var readings = Wh.Select((wh, i) =>
        {
            var kwh = wh / 1000m;
            return new Reading(start.AddMinutes(15 * i), start.AddMinutes(15 * (i + 1)), kwh, kwh * 4);
        }).ToList();
        return new ParsedFile(Name, null, readings, 0);
    }
}
