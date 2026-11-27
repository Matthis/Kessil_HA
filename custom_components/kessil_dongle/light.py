"""Light entity: on/off and intensity of a lamp group."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.light import ATTR_BRIGHTNESS, ColorMode, LightEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import ExtraStoredData, RestoreEntity

from .api import UI_CHANNELS
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


@dataclass
class KessilLightExtraData(ExtraStoredData):
    last_on_ui: list[int] | None

    def as_dict(self) -> dict[str, Any]:
        return {"last_on_ui": self.last_on_ui}


class KessilLight(KessilGroupEntity, LightEntity, RestoreEntity):
    """On/off for all light-emitting channels, brightness = intensity.

    Any change switches the group to manual mode. Turning off zeroes every
    emitting channel (intensity, and on Tuna Sun also red and amber); the
    values before turning off are remembered (also across restarts) and
    restored on the next turn-on.
    """

    _attr_name = None
    _attr_color_mode = ColorMode.BRIGHTNESS
    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}

    def __init__(self, coordinator: KessilCoordinator, gid: int) -> None:
        super().__init__(coordinator, gid, "light")
        self._last_on_ui: tuple[int, ...] | None = None
        self._remember_if_on()

    @property
    def _channels(self) -> tuple[int, ...]:
        return light_channels(self.group.type)

    @property
    def brightness(self) -> int:
        return self.coordinator.current_ui(self.gid)[CH_INTENSITY]

    @property
    def is_on(self) -> bool:
        return not self.coordinator.is_dark(self.gid)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"manual": self.group.is_manual, "group_id": self.gid}

    @property
    def extra_restore_state_data(self) -> KessilLightExtraData:
        return KessilLightExtraData(list(self._last_on_ui) if self._last_on_ui else None)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if self._last_on_ui is None and (data := await self.async_get_last_extra_data()):
            stored = data.as_dict().get("last_on_ui")
            if isinstance(stored, list) and len(stored) == UI_CHANNELS:
                self._last_on_ui = tuple(int(v) for v in stored)

    def _remember_if_on(self) -> None:
        if self.gid in self.coordinator.data.groups and self.is_on:
            self._last_on_ui = self.coordinator.current_ui(self.gid)

    @callback
    def _handle_coordinator_update(self) -> None:
        self._remember_if_on()
        super()._handle_coordinator_update()

    async def async_turn_on(self, **kwargs: Any) -> None:
        brightness = kwargs.get(ATTR_BRIGHTNESS)
        if self.is_on:
            if brightness is not None:
                await self.coordinator.async_set_channels(
                    self.gid, {CH_INTENSITY: max(1, int(brightness))}
                )
            return
        if self._last_on_ui is not None:
            changes = {idx: self._last_on_ui[idx] for idx in self._channels}
        else:  # nothing remembered: use the dongle's stored manual values
            changes = {idx: self.group.ui[idx] for idx in self._channels}
        if brightness is not None:
            changes[CH_INTENSITY] = max(1, int(brightness))
        if all(v == 0 for v in changes.values()):
            changes[CH_INTENSITY] = DEFAULT_BRIGHTNESS
        await self.coordinator.async_set_channels(self.gid, changes)

    async def async_turn_off(self, **kwargs: Any) -> None:
        self._remember_if_on()
        await self.coordinator.async_set_channels(self.gid, dict.fromkeys(self._channels, 0))
