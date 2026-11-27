"""Sensors on the group device: lamp count, overheat status per lamp (diagnostic)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import Lamp
from .const import DOMAIN
from .coordinator import KessilConfigEntry, KessilCoordinator
from .entity import KessilGroupEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: KessilConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    entities: list[SensorEntity] = [
        KessilLampCountSensor(coordinator, gid) for gid in coordinator.data.groups
    ]
    for gid in coordinator.data.groups:
        lamps = sorted(
            (lamp for lamp in coordinator.data.system.lamps if lamp.gid == gid),
            key=lambda lamp: lamp.kid,
        )
        entities += [
            KessilLampTempSensor(coordinator, gid, lamp.kid, number)
            for number, lamp in enumerate(lamps, start=1)
        ]
    async_add_entities(entities)


class KessilLampCountSensor(KessilGroupEntity, SensorEntity):
    _attr_translation_key = "lamp_count"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: KessilCoordinator, gid: int) -> None:
        super().__init__(coordinator, gid, "lamp_count")

    @property
    def native_value(self) -> int:
        return self.group.lamp_count


class KessilLampTempSensor(CoordinatorEntity[KessilCoordinator], SensorEntity):
    """Raw `temp` field of a lamp; 0 when normal (meaning not fully known)."""

    _attr_has_entity_name = True
    _attr_translation_key = "overheat"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: KessilCoordinator, gid: int, kid: int, number: int) -> None:
        super().__init__(coordinator)
        self.kid = kid
        serial = coordinator.data.system.serial
        self._attr_unique_id = f"lamp_{kid}_overheat"
        self._attr_translation_placeholders = {"lamp": str(number)}
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, f"{serial}_group_{gid}")})

    @property
    def _lamp(self) -> Lamp | None:
        return next((l for l in self.coordinator.data.system.lamps if l.kid == self.kid), None)

    @property
    def available(self) -> bool:
        return super().available and self._lamp is not None

    @property
    def native_value(self) -> int | None:
        lamp = self._lamp
        return lamp.temp if lamp else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        lamp = self._lamp
        if lamp is None:
            return {}
        return {"lamp_id": lamp.kid, "model": lamp.model, "firmware": lamp.firmware}
