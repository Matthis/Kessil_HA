"""Base entities for the Kessil WiFi dongle."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import Group
from .const import DOMAIN
from .coordinator import KessilCoordinator


class KessilGroupEntity(CoordinatorEntity[KessilCoordinator]):
    """Entity bound to one lamp group (the unit the dongle controls)."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: KessilCoordinator, gid: int, key: str) -> None:
        super().__init__(coordinator)
        self.gid = gid
        serial = coordinator.data.system.serial
        self._attr_unique_id = f"{serial}_group_{gid}_{key}"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, f"{serial}_group_{gid}")})

    @property
    def group(self) -> Group:
        return self.coordinator.data.groups[self.gid]

    @property
    def available(self) -> bool:
        return super().available and self.gid in self.coordinator.data.groups
