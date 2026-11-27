"""Light entity: on/off and intensity of a lamp group."""

from __future__ import annotations

from typing import Any

from homeassistant.components.light import ATTR_BRIGHTNESS, ColorMode, LightEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import CH_INTENSITY, DEFAULT_BRIGHTNESS
from .coordinator import KessilConfigEntry, KessilCoordinator
from .entity import KessilGroupEntity

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: KessilConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(KessilLight(coordinator, gid) for gid in coordinator.data.groups)


class KessilLight(KessilGroupEntity, LightEntity):
    """Intensity channel. Any change switches the group to manual mode."""

    _attr_name = None
    _attr_color_mode = ColorMode.BRIGHTNESS
    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}

    def __init__(self, coordinator: KessilCoordinator, gid: int) -> None:
        super().__init__(coordinator, gid, "light")
        current = coordinator.current_ui(gid)[CH_INTENSITY]
        self._last_brightness = current or DEFAULT_BRIGHTNESS

    @property
    def brightness(self) -> int:
        return self.coordinator.current_ui(self.gid)[CH_INTENSITY]

    @property
    def is_on(self) -> bool:
        return self.brightness > 0

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"manual": self.group.is_manual, "group_id": self.gid}

    @callback
    def _handle_coordinator_update(self) -> None:
        if self.gid in self.coordinator.data.groups and self.brightness > 0:
            self._last_brightness = self.brightness
        super()._handle_coordinator_update()

    async def async_turn_on(self, **kwargs: Any) -> None:
        if (brightness := kwargs.get(ATTR_BRIGHTNESS)) is None:
            if self.is_on:
                return
            brightness = self._last_brightness
        await self.coordinator.async_set_channels(self.gid, {CH_INTENSITY: max(1, int(brightness))})

    async def async_turn_off(self, **kwargs: Any) -> None:
        if self.is_on:
            self._last_brightness = self.brightness
        await self.coordinator.async_set_channels(self.gid, {CH_INTENSITY: 0})
