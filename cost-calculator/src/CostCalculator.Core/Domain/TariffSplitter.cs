using System.Globalization;

namespace CostCalculator.Domain;

public enum SplitMode { HdoSchedule, FixedShare }

/// <summary>User's VT/NT split settings (specification section 5).</summary>
public sealed class SplitSettings
{
    public SplitMode Mode { get; set; } = SplitMode.FixedShare;
    /// <summary>VT windows Mon-Fri, e.g. "07:00-08:00, 11:00-12:00".</summary>
    public string WeekdayWindows { get; set; } = "";
    /// <summary>VT windows Sat-Sun.</summary>
    public string WeekendWindows { get; set; } = "";
    /// <summary>Percent of consumption counted as VT in fixed mode (last invoice: 127/788 = 16.1 %).</summary>
    public decimal VtSharePercent { get; set; } = 16.1m;
    /// <summary>VT hours per day of the tariff; D57d has 20 NT hours, so VT windows must total 4 h.</summary>
    public decimal ExpectedVtHoursPerDay { get; set; } = 4m;
}

public readonly record struct TimeWindow(int StartMinute, int EndMinute)
{
    public bool Contains(int minuteOfDay) =>
        StartMinute < EndMinute
            ? minuteOfDay >= StartMinute && minuteOfDay < EndMinute
            : minuteOfDay >= StartMinute || minuteOfDay < EndMinute; // crosses midnight

    public int Length => StartMinute < EndMinute ? EndMinute - StartMinute : 1440 - StartMinute + EndMinute;
}

public static class TariffSplitter
{
    /// <summary>Parses "07:00-08:00, 11:00-12:00". Returns an error text, or null when valid.</summary>
    public static string? TryParseWindows(string text, out List<TimeWindow> windows)
    {
        windows = new List<TimeWindow>();
        if (string.IsNullOrWhiteSpace(text)) return null;

        var separators = new[] { ',', ';', '\n' };
        foreach (var part in text.Split(separators, StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries))
        {
            var ends = part.Split(new[] { '-', '–' }, StringSplitOptions.TrimEntries);
            if (ends.Length != 2 || !TryParseTime(ends[0], out var s) || !TryParseTime(ends[1], out var e) || s == e)
                return $"Neplatný úsek „{part}“. Použijte tvar 07:00-08:00.";
            windows.Add(new TimeWindow(s, e));
        }
        return null;
    }

    private static bool TryParseTime(string text, out int minute)
    {
        minute = 0;
        var bits = text.Split(':');
        if (bits.Length is < 1 or > 2) return false;
        if (!int.TryParse(bits[0], NumberStyles.None, CultureInfo.InvariantCulture, out var h)) return false;
        var m = 0;
        if (bits.Length == 2 && !int.TryParse(bits[1], NumberStyles.None, CultureInfo.InvariantCulture, out m)) return false;
        if (h is < 0 or > 24 || m is < 0 or > 59 || (h == 24 && m != 0)) return false;
        minute = (h * 60 + m) % 1440;
        return true;
    }

    public static decimal TotalHours(IEnumerable<TimeWindow> windows) => windows.Sum(w => w.Length) / 60m;

    /// <summary>Warnings about the HDO windows (empty list = fine).</summary>
    public static List<string> Validate(SplitSettings s)
    {
        var warnings = new List<string>();
        if (s.Mode != SplitMode.HdoSchedule) return warnings;

        foreach (var (label, text) in new[] { ("pracovní dny", s.WeekdayWindows), ("víkend", s.WeekendWindows) })
        {
            var error = TryParseWindows(text, out var w);
            if (error != null) warnings.Add($"{label}: {error}");
            else if (w.Count == 0) warnings.Add($"{label}: nejsou zadána žádná okna VT.");
            else if (TotalHours(w) != s.ExpectedVtHoursPerDay)
                warnings.Add($"{label}: okna VT dávají {TotalHours(w):0.##} h, očekává se {s.ExpectedVtHoursPerDay:0.##} h denně.");
        }
        return warnings;
    }

    /// <summary>Returns a function giving the VT kWh of a reading (the rest is NT).</summary>
    public static Func<Reading, decimal> CreateVtFunc(SplitSettings s)
    {
        if (s.Mode == SplitMode.FixedShare)
        {
            var share = Math.Clamp(s.VtSharePercent, 0m, 100m) / 100m;
            return r => r.Kwh * share;
        }

        TryParseWindows(s.WeekdayWindows, out var weekday);
        TryParseWindows(s.WeekendWindows, out var weekend);
        return r =>
        {
            var windows = r.Start.DayOfWeek is DayOfWeek.Saturday or DayOfWeek.Sunday ? weekend : weekday;
            var minute = r.Start.Hour * 60 + r.Start.Minute; // an interval is VT if its start is in a window
            return windows.Any(w => w.Contains(minute)) ? r.Kwh : 0m;
        };
    }

    /// <summary>For the chart background band: whether a time of day is VT. Null in fixed-share mode.</summary>
    public static Func<DateTime, bool>? CreateIsVtFunc(SplitSettings s)
    {
        if (s.Mode != SplitMode.HdoSchedule) return null;
        TryParseWindows(s.WeekdayWindows, out var weekday);
        TryParseWindows(s.WeekendWindows, out var weekend);
        return t =>
        {
            var windows = t.DayOfWeek is DayOfWeek.Saturday or DayOfWeek.Sunday ? weekend : weekday;
            var minute = t.Hour * 60 + t.Minute;
            return windows.Any(w => w.Contains(minute));
        };
    }
}
