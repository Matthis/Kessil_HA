"""Light entity: on/off and intensity of a lamp group."""

from __future__ import annotations

from typing import Any

from homeassistant.components.light import ATTR_BRIGHTNESS, ColorMode, LightEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import CH_INTENSITY, DEFAULT_BRIGHTNESS, light_channels
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
    """Shows the operating state of a lamp group; brightness = intensity.

    On: a program runs (even while its values are 0), or manual mode with
    intensity, red or amber above 0 (red and amber are separate LEDs on
    Tuna Sun). Off: manual mode with all of them at 0.

    Commands: off -> manual, those channels 0. On with brightness -> manual
    with that intensity. On without brightness -> manual with the intensity
    stored in the dongle (or ~50 % if that is 0). Nothing is remembered in
    Home Assistant.
    """

    _attr_name = None
    _attr_color_mode = ColorMode.BRIGHTNESS
    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}

    def __init__(self, coordinator: KessilCoordinator, gid: int) -> None:
        super().__init__(coordinator, gid, "light")

    @property
    def _channels(self) -> tuple[int, ...]:
        return light_channels(self.group.type)

    @property
    def brightness(self) -> int:
        return self.coordinator.current_ui(self.gid)[CH_INTENSITY]

    @property
    def is_on(self) -> bool:
        group = self.group
        if not group.is_manual:
            return True
        return any(group.ui[idx] > 0 for idx in self._channels)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        lamps = self.coordinator.data.system.lamps
        return {
            "manual": self.group.is_manual,
            "group_id": self.gid,
            "lamp_models": sorted({lamp.model for lamp in lamps if lamp.gid == self.gid}),
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        brightness = kwargs.get(ATTR_BRIGHTNESS)
        if brightness is not None:
            await self.coordinator.async_set_channels(
                self.gid, {CH_INTENSITY: max(1, int(brightness))}
            )
        elif not self.is_on:
            stored = self.group.ui[CH_INTENSITY]
            await self.coordinator.async_set_channels(
                self.gid, {CH_INTENSITY: stored or DEFAULT_BRIGHTNESS}
            )

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_channels(self.gid, dict.fromkeys(self._channels, 0))
