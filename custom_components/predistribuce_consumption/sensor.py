"""Diagnostic sensor: newest day imported. Updating it forces a fetch."""
from __future__ import annotations

import datetime

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import PortalConfigEntry
from .const import CONF_EAN
from .coordinator import PortalCoordinator
from .entity import HdoEntity
from .hdo import next_start


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PortalConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    data = entry.runtime_data
    entities: list[SensorEntity] = [LastImportedDaySensor(data.portal, entry)]
    if data.hdo is not None:
        entities += [
            HdoNextStartSensor(data.hdo, entry, low=True),
            HdoNextStartSensor(data.hdo, entry, low=False),
        ]
    async_add_entities(entities)


class LastImportedDaySensor(CoordinatorEntity[PortalCoordinator], SensorEntity):
    _attr_has_entity_name = True
    _attr_name = "Last imported day"
    _attr_device_class = SensorDeviceClass.DATE
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: PortalCoordinator, entry: PortalConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.data[CONF_EAN]}_last_imported_day"

    @property
    def native_value(self) -> datetime.date | None:
        return self.coordinator.data


class HdoNextStartSensor(HdoEntity, SensorEntity):
    """When the next low (or high) tariff period starts."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator, entry: PortalConfigEntry, *, low: bool) -> None:
        key = "next_low_tariff_start" if low else "next_high_tariff_start"
        super().__init__(coordinator, entry, key)
        self._low = low
        self._attr_name = "Next low tariff start" if low else "Next high tariff start"

    @property
    def native_value(self) -> datetime.datetime | None:
        return next_start(self.intervals, self.now, self._low)
