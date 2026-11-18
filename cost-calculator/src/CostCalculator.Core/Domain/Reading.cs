namespace CostCalculator.Domain;

/// <summary>One 15-minute interval from the export; timestamps are local wall-clock time.</summary>
/// <param name="Occurrence">0 normally; 1 for the repeated hour on the autumn DST change.</param>
public sealed record Reading(DateTime Start, DateTime End, decimal Kwh, decimal? Kw, int Occurrence = 0);
