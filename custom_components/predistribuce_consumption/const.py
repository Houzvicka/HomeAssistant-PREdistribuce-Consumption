"""Constants for the PREdistribuce consumption integration."""
from datetime import timedelta

DOMAIN = "predistribuce_consumption"

CONF_EAN = "ean"
CONF_BACKFILL_DAYS = "backfill_days"

DEFAULT_BACKFILL_DAYS = 30
MAX_BACKFILL_DAYS = 800

# The portal has a one-day lag, so polling faster than daily gains nothing.
UPDATE_INTERVAL = timedelta(days=1)

# Each run re-fetches this many days before the newest imported hour, to
# absorb late corrections the portal makes to recent days.
REFETCH_DAYS = 3

# Timezone of the portal's naive timestamps.
PORTAL_TIMEZONE = "Europe/Prague"

# unit_class of the recorder's energy unit converter (EnergyConverter).
UNIT_CLASS_ENERGY = "energy"

# HDO (low/high tariff schedule). Optional: the receiver command code
# ("povel") from the meter / contract. Unset or empty = HDO disabled.
CONF_HDO_COMMAND = "hdo_command"

# The public schedule covers ~2 weeks ahead and rarely changes; the entities
# switch on their own timers, so this only has to pick up plan changes.
HDO_UPDATE_INTERVAL = timedelta(hours=6)

# With an HDO code set, consumption is also written as two extra statistics
# split by tariff (statistic ids "<domain>:<ean>_nt" / "..._vt"). History is
# split from the portal's real per-day HDO record, one request per day.
CONF_HDO_HISTORY_DAYS = "hdo_history_days"
DEFAULT_HDO_HISTORY_DAYS = 120  # only used until split statistics exist
MAX_HDO_HISTORY_DAYS = 400
SUFFIX_NT = "_nt"
SUFFIX_VT = "_vt"
STAT_LABELS = {
    "": "",
    SUFFIX_NT: " - low tariff (NT)",
    SUFFIX_VT: " - high tariff (VT)",
}

# Optional all-in prices (CZK per kWh, incl. VAT) per tariff. With a price set,
# a cost statistic "<ean>_nt_cost" / "<ean>_vt_cost" (in CZK) is written next
# to the matching consumption statistic. The Energy dashboard cannot apply a
# static price to an external statistic, but can use a cost statistic via
# "Use an entity tracking the total costs".
CONF_PRICE_NT = "price_nt"
CONF_PRICE_VT = "price_vt"
COST_SUFFIX = "_cost"
COST_CURRENCY = "CZK"
STAT_LABELS.update(
    {
        SUFFIX_NT + COST_SUFFIX: " - low tariff (NT) cost",
        SUFFIX_VT + COST_SUFFIX: " - high tariff (VT) cost",
    }
)


def get_price(entry, key: str) -> float | None:
    """A configured price; options override data. None/0 = no cost statistic."""
    value = entry.options.get(key, entry.data.get(key))
    return float(value) if value else None


def get_hdo_command(entry) -> str | None:
    """The configured HDO command code; options override the original data."""
    value = entry.options.get(CONF_HDO_COMMAND, entry.data.get(CONF_HDO_COMMAND))
    return (value or "").strip() or None
