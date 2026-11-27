"""Mode select: manual or one of the dongle's stored programs."""

from __future__ import annotations

from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import MANUAL_PID, Program
from .coordinator import KessilConfigEntry, KessilCoordinator
from .entity import KessilGroupEntity

PARALLEL_UPDATES = 1

OPTION_MANUAL = "manual"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: KessilConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(KessilModeSelect(coordinator, gid) for gid in coordinator.data.groups)


def program_options(programs: list[Program]) -> dict[str, Program]:
    """Option label -> program; duplicate names get the PID appended."""
    names = [p.name for p in programs]
    options: dict[str, Program] = {}
    for program in programs:
        label = program.name
        if names.count(label) > 1 or label == OPTION_MANUAL:
            label = f"{label} ({program.pid})"
        options[label] = program
    return options


def points_as_lists(program: Program) -> list[list[int]]:
    """Compact form for the card: [minutes, ch1, ch2, ch3, ch4, ch5]."""
    return [[p.minutes, *p.ui] for p in program.points]


class KessilModeSelect(KessilGroupEntity, SelectEntity):
    _attr_translation_key = "mode"
    _unrecorded_attributes = frozenset({"programs"})

    def __init__(self, coordinator: KessilCoordinator, gid: int) -> None:
        super().__init__(coordinator, gid, "mode")

    @property
    def _programs(self) -> dict[str, Program]:
        return program_options(self.coordinator.data.programs_for(self.group))

    @property
    def options(self) -> list[str]:
        return [OPTION_MANUAL, *self._programs]

    @property
    def current_option(self) -> str | None:
        group = self.group
        if group.is_manual:
            return OPTION_MANUAL
        for label, program in self._programs.items():
            if program.pid == group.pid:
                return label
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        group = self.group
        return {
            "program_id": None if group.is_manual else group.pid,
            "programs": {
                label: points_as_lists(program) for label, program in self._programs.items()
            },
        }

    async def async_select_option(self, option: str) -> None:
        pid = MANUAL_PID if option == OPTION_MANUAL else self._programs[option].pid
        await self.coordinator.async_run_program(self.gid, pid)
