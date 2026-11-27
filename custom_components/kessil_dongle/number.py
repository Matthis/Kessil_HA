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


def raw_to_percent(raw: int, maximum: int = 255) -> int:
    return max(0, min(100, round(raw * 100 / maximum)))


def percent_to_raw(percent: float, maximum: int = 255) -> int:
    return max(0, min(maximum, round(percent * maximum / 100)))


async def async_setup_entry(
    hass: HomeAssistant,
    entry: KessilConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        KessilChannelNumber(coordinator, gid, key, idx, maximum)
        for gid, group in coordinator.data.groups.items()
        for key, (idx, maximum) in EXTRA_CHANNELS.get(group.type, DEFAULT_EXTRA_CHANNELS).items()
    )


class KessilChannelNumber(KessilGroupEntity, NumberEntity):
    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_mode = NumberMode.SLIDER

    def __init__(
        self, coordinator: KessilCoordinator, gid: int, key: str, index: int, maximum: int
    ) -> None:
        super().__init__(coordinator, gid, key)
        self._attr_translation_key = key
        self._index = index
        self._max = maximum

    @property
    def native_value(self) -> int:
        return raw_to_percent(self.coordinator.current_ui(self.gid)[self._index], self._max)

    async def async_set_native_value(self, value: float) -> None:
        raw = percent_to_raw(value, self._max)
        await self.coordinator.async_set_channels(self.gid, {self._index: raw})
