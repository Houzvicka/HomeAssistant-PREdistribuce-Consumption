"""Base entity for HDO: re-evaluates itself exactly when the tariff switches."""
from __future__ import annotations

import datetime

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.event import async_track_point_in_time
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .hdo import Interval, next_boundary
from .hdo_coordinator import HdoCoordinator


class HdoEntity(CoordinatorEntity[HdoCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: HdoCoordinator, entry: ConfigEntry, key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_hdo_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry.entry_id}_hdo")},
            name=f"PREdistribuce HDO {coordinator.command}",
            manufacturer="PREdistribuce",
            entry_type=DeviceEntryType.SERVICE,
        )
        self._unsub_boundary: CALLBACK_TYPE | None = None

    @property
    def intervals(self) -> list[Interval]:
        return self.coordinator.data or []

    @property
    def now(self) -> datetime.datetime:
        return dt_util.utcnow()

    @property
    def available(self) -> bool:
        # The schedule covers ~2 weeks, so keep working on the last good copy
        # while a refresh is failing instead of flipping to unavailable.
        return self.coordinator.data is not None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._arm_boundary_timer()

    async def async_will_remove_from_hass(self) -> None:
        self._cancel_boundary_timer()
        await super().async_will_remove_from_hass()

    @callback
    def _handle_coordinator_update(self) -> None:
        self._arm_boundary_timer()
        super()._handle_coordinator_update()

    def _cancel_boundary_timer(self) -> None:
        if self._unsub_boundary is not None:
            self._unsub_boundary()
            self._unsub_boundary = None

    def _arm_boundary_timer(self) -> None:
        self._cancel_boundary_timer()
        boundary = next_boundary(self.intervals, self.now)
        if boundary is not None:
            self._unsub_boundary = async_track_point_in_time(
                self.hass, self._on_boundary, boundary
            )

    @callback
    def _on_boundary(self, _now: datetime.datetime) -> None:
        self._unsub_boundary = None
        self.async_write_ha_state()
        self._arm_boundary_timer()
