"""HDO binary sensor: is the low tariff (nízký tarif, NT) active right now."""
from __future__ import annotations

import datetime
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from . import PortalConfigEntry
from .entity import HdoEntity
from .hdo import current_interval

SCHEDULE_HORIZON = datetime.timedelta(hours=48)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PortalConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    hdo = entry.runtime_data.hdo
    if hdo is not None:
        async_add_entities([HdoLowTariffSensor(hdo, entry)])


class HdoLowTariffSensor(HdoEntity, BinarySensorEntity):
    _attr_name = "Low tariff"

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry, "low_tariff")

    @property
    def is_on(self) -> bool | None:
        # None (unknown) if the schedule does not cover the current moment.
        current = current_interval(self.intervals, self.now)
        return None if current is None else current.low

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        now = self.now
        current = current_interval(self.intervals, now)
        upcoming = [
            {
                "start": dt_util.as_local(i.start).isoformat(),
                "end": dt_util.as_local(i.end).isoformat(),
                "tariff": "low" if i.low else "high",
            }
            for i in self.intervals
            if i.end > now and i.start < now + SCHEDULE_HORIZON
        ]
        return {
            "current_ends": (
                dt_util.as_local(current.end).isoformat() if current else None
            ),
            "schedule": upcoming,
        }
