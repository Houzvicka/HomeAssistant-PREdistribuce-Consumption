using System.Globalization;
using System.Text;
using System.Text.RegularExpressions;
using CostCalculator.Domain;

namespace CostCalculator.Import;

public sealed record ParsedFile(string Name, string? Ean, List<Reading> Readings, int SkippedLines);

/// <summary>Parser of the PREdistribuce 15-minute export (specification section 3).</summary>
public static class CsvParser
{
    private static readonly Regex RowPattern = new(
        @"^\s*(\d{2}\.\d{2}\.\d{4} \d{2}:\d{2});(\d{2}\.\d{2}\.\d{4} \d{2}:\d{2});(-?[\d\s]+(?:,\d+)?);(?:(-?[\d\s]+(?:,\d+)?);)?",
        RegexOptions.Compiled);

    private static readonly Regex EanPattern = new(@"(\d{15,})\s*-", RegexOptions.Compiled);

    private const string TimeFormat = "dd.MM.yyyy HH:mm";

    static CsvParser() => Encoding.RegisterProvider(CodePagesEncodingProvider.Instance);

    /// <summary>UTF-8 first (strict); Windows-1250 when the bytes are not valid UTF-8.</summary>
    public static string Decode(byte[] bytes)
    {
        try
        {
            var utf8 = new UTF8Encoding(false, throwOnInvalidBytes: true);
            var text = utf8.GetString(bytes);
            return text.TrimStart('﻿');
        }
        catch (DecoderFallbackException)
        {
            return Encoding.GetEncoding(1250).GetString(bytes);
        }
    }

    public static ParsedFile Parse(string name, byte[] bytes) => ParseText(name, Decode(bytes));

    public static ParsedFile ParseText(string name, string text)
    {
        string? ean = null;
        var readings = new List<Reading>();
        var skipped = 0;
        // The same start time appearing again inside one file is the repeated hour of the
        // autumn DST change, not a duplicate; it gets Occurrence 1 so it is not discarded.
        var seen = new Dictionary<DateTime, int>();

        foreach (var line in text.Split('\n'))
        {
            var row = RowPattern.Match(line);
            if (!row.Success)
            {
                if (ean == null && EanPattern.Match(line) is { Success: true } m) ean = m.Groups[1].Value;
                else if (!string.IsNullOrWhiteSpace(line)) skipped++;
                continue;
            }

            var start = DateTime.ParseExact(row.Groups[1].Value, TimeFormat, CultureInfo.InvariantCulture);
            var end = DateTime.ParseExact(row.Groups[2].Value, TimeFormat, CultureInfo.InvariantCulture);
            var kwh = ParseNumber(row.Groups[3].Value);
            decimal? kw = row.Groups[4].Success ? ParseNumber(row.Groups[4].Value) : null;

            seen.TryGetValue(start, out var occurrence);
            seen[start] = occurrence + 1;
            readings.Add(new Reading(start, end, kwh, kw, occurrence));
        }
        return new ParsedFile(name, ean, readings, skipped);
    }

    private static decimal ParseNumber(string text) =>
        decimal.Parse(text.Replace(" ", "").Replace(',', '.'), CultureInfo.InvariantCulture);

    /// <summary>Merges files and de-duplicates by interval start (later files win).</summary>
    public static List<Reading> Merge(IEnumerable<ParsedFile> files)
    {
        var merged = new Dictionary<(DateTime, int), Reading>();
        foreach (var file in files)
            foreach (var r in file.Readings)
                merged[(r.Start, r.Occurrence)] = r;
        return merged.Values.OrderBy(r => r.Start).ThenBy(r => r.Occurrence).ToList();
    }
}
