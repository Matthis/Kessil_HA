"""Number entities for the spectrum channels (color, red, amber) in percent."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DEFAULT_EXTRA_CHANNELS, EXTRA_CHANNELS
from .coordinator import KessilConfigEntry, KessilCoordinator
from .entity import KessilGroupEntity

PARALLEL_UPDATES = 1


def raw_to_percent(raw: int) -> int:
    return round(raw * 100 / 255)


def percent_to_raw(percent: float) -> int:
    return max(0, min(255, round(percent * 255 / 100)))


async def async_setup_entry(
    hass: HomeAssistant,
    entry: KessilConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        KessilChannelNumber(coordinator, gid, key, idx)
        for gid, group in coordinator.data.groups.items()
        for key, idx in EXTRA_CHANNELS.get(group.type, DEFAULT_EXTRA_CHANNELS).items()
    )


class KessilChannelNumber(KessilGroupEntity, NumberEntity):
    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_mode = NumberMode.SLIDER

    def __init__(self, coordinator: KessilCoordinator, gid: int, key: str, index: int) -> None:
        super().__init__(coordinator, gid, key)
        self._attr_translation_key = key
        self._index = index

    @property
    def native_value(self) -> int:
        return raw_to_percent(self.coordinator.current_ui(self.gid)[self._index])

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_set_channels(self.gid, {self._index: percent_to_raw(value)})
