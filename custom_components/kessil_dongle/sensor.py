"""Sensors: lamp count per group, overheat status per lamp (diagnostic)."""

from __future__ import annotations

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
    entities += [
        KessilLampTempSensor(coordinator, lamp.kid) for lamp in coordinator.data.system.lamps
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

    def __init__(self, coordinator: KessilCoordinator, kid: int) -> None:
        super().__init__(coordinator)
        self.kid = kid
        self._attr_unique_id = f"lamp_{kid}_overheat"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, f"lamp_{kid}")})

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
