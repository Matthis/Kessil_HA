"""Polling coordinator for the Kessil WiFi dongle."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    MANUAL_PID,
    MAX_PROGRAMS_PER_TYPE,
    TYPE_KEYS,
    Group,
    KessilDongle,
    KessilError,
    Program,
    SystemInfo,
    is_preset,
    parse_points,
    validate_name,
)
from .const import DOMAIN, SCAN_INTERVAL, SLOW_REFRESH_EVERY

_LOGGER = logging.getLogger(__name__)

type KessilConfigEntry = ConfigEntry[KessilCoordinator]


@dataclass(slots=True)
class KessilData:
    system: SystemInfo
    groups: dict[int, Group]
    # (type, pid) -> program
    programs: dict[tuple[int, int], Program] = field(default_factory=dict)

    def programs_for(self, group: Group) -> list[Program]:
        """Programs usable by a group, in dongle order (manual excluded)."""
        pids = self.system.program_ids.get(group.type_key or "", ())
        return [
            self.programs[(group.type, pid)] for pid in pids if (group.type, pid) in self.programs
        ]

    def current_ui(self, group: Group, now: datetime) -> tuple[int, ...]:
        """What the lamps actually show right now.

        In manual mode that is the group's `UI`. While a program runs, `UI`
        still holds the stored manual values, so the output is computed from
        the program curve at the dongle's local time.
        """
        if group.is_manual:
            return group.ui
        program = self.programs.get((group.type, group.pid))
        if program is None:
            return group.ui
        local = now.astimezone(_zone(self.system.timezone))
        value = program.value_at(local.hour * 60 + local.minute + local.second / 60)
        return value if value is not None else group.ui


class KessilCoordinator(DataUpdateCoordinator[KessilData]):
    """Polls all groups that have lamps; refreshes slow data occasionally."""

    config_entry: KessilConfigEntry

    def __init__(self, hass: HomeAssistant, entry: KessilConfigEntry, client: KessilDongle) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=SCAN_INTERVAL,
        )
        self.client = client
        self._polls = 0

    async def _async_update_data(self) -> KessilData:
        try:
            if self.data is None or self._polls % SLOW_REFRESH_EVERY == 0:
                system = await self.client.get_system_info()
                programs = await self._fetch_programs(system)
            else:
                system = self.data.system
                programs = self.data.programs
            gids = sorted({lamp.gid for lamp in system.lamps if lamp.gid >= 0})
            groups = {gid: await self.client.get_group(gid) for gid in gids}
        except KessilError as err:
            raise UpdateFailed(str(err)) from err
        self._polls += 1
        return KessilData(system=system, groups=groups, programs=programs)

    async def _fetch_programs(self, system: SystemInfo) -> dict[tuple[int, int], Program]:
        """Load the programs for every lamp type that is actually in use."""
        programs: dict[tuple[int, int], Program] = {}
        types = {lamp.type for lamp in system.lamps}
        key_to_type = {TYPE_KEYS[t]: t for t in types if t in TYPE_KEYS}
        for key, type_ in key_to_type.items():
            for pid in system.program_ids.get(key, ()):
                if pid == MANUAL_PID:
                    continue
                try:
                    programs[(type_, pid)] = await self.client.get_program(pid, type_)
                except KessilError as err:
                    _LOGGER.debug("Program %s/%s not readable: %s", type_, pid, err)
        return programs

    def current_ui(self, gid: int) -> tuple[int, ...]:
        return self.data.current_ui(self.data.groups[gid], dt_util.now())

    # --- write helpers used by the entities ---------------------------------

    async def async_set_channels(self, gid: int, changes: dict[int, int]) -> None:
        """Switch the group to manual (if needed) and set channel values.

        Channels not in `changes` keep the manual values stored in the dongle
        (which is also what the dongle itself switches to in manual mode).
        Nothing is remembered in Home Assistant.
        """
        group = self.data.groups[gid]
        ui = list(group.ui)
        for idx, value in changes.items():
            ui[idx] = max(0, min(255, int(value)))
        try:
            if not group.is_manual:
                await self.client.run_program(gid, MANUAL_PID)
            await self.client.set_manual(gid, ui, save=True)
        except KessilError as err:
            raise HomeAssistantError(f"Kessil dongle: {err}") from err
        self._store_group(replace(group, pid=MANUAL_PID, ui=tuple(ui)))

    async def async_run_program(self, gid: int, pid: int) -> None:
        try:
            await self.client.run_program(gid, pid)
            group = await self.client.get_group(gid)
        except KessilError as err:
            raise HomeAssistantError(f"Kessil dongle: {err}") from err
        self._store_group(group)

    # --- program management (HA actions) -----------------------------------

    def find_program(self, type_: int, name: str) -> Program:
        """A program of this lamp type by name (or by "name (PID)" label)."""
        programs = [p for (t, _), p in self.data.programs.items() if t == type_]
        for program in programs:
            if name in (program.name, f"{program.name} ({program.pid})"):
                return program
        raise HomeAssistantError(f"No program named '{name}' for this lamp type")

    async def async_save_program(self, type_: int, name: str, raw_points: list[dict]) -> Program:
        """Create a program, or overwrite the user program with the same name."""
        try:
            name = validate_name(name)
            points = parse_points(raw_points, type_)
        except ValueError as err:
            raise HomeAssistantError(str(err)) from err
        existing = [p for (t, _), p in self.data.programs.items() if t == type_ and p.name == name]
        if existing:
            pid = existing[0].pid
            if is_preset(type_, pid):
                raise HomeAssistantError(f"'{name}' is a preset and cannot be overwritten")
        else:
            used = set(self.data.system.program_ids.get(TYPE_KEYS.get(type_, ""), ()))
            if len(used - {MANUAL_PID}) >= MAX_PROGRAMS_PER_TYPE:
                raise HomeAssistantError(
                    f"The dongle already holds {MAX_PROGRAMS_PER_TYPE} programs for this lamp type"
                )
            pid = min(set(range(1, MAX_PROGRAMS_PER_TYPE + 2)) - used)
        program = Program(pid=pid, type=type_, name=name, points=points)
        await self._write(self.client.save_program(program))
        return program

    async def async_rename_program(self, type_: int, name: str, new_name: str) -> None:
        program = self._user_program(type_, name, "renamed")
        try:
            new_name = validate_name(new_name)
        except ValueError as err:
            raise HomeAssistantError(str(err)) from err
        await self._write(self.client.rename_program(program.pid, type_, new_name))

    async def async_delete_program(self, type_: int, name: str) -> None:
        program = self._user_program(type_, name, "deleted")
        running = [g for g in self.data.groups.values() if g.type == type_ and g.pid == program.pid]
        if running:
            raise HomeAssistantError(
                f"'{program.name}' is running; switch the group to another mode first"
            )
        await self._write(self.client.delete_program(program.pid, type_))

    def _user_program(self, type_: int, name: str, action: str) -> Program:
        program = self.find_program(type_, name)
        if is_preset(type_, program.pid):
            raise HomeAssistantError(f"'{program.name}' is a preset and cannot be {action}")
        return program

    async def _write(self, command) -> None:
        """Send a program command, then reload the program list."""
        try:
            await command
            system = await self.client.get_system_info()
            programs = await self._fetch_programs(system)
        except KessilError as err:
            raise HomeAssistantError(f"Kessil dongle: {err}") from err
        except ValueError as err:
            raise HomeAssistantError(str(err)) from err
        self.async_set_updated_data(replace(self.data, system=system, programs=programs))

    def _store_group(self, group: Group) -> None:
        groups = dict(self.data.groups)
        groups[group.gid] = group
        self.async_set_updated_data(replace(self.data, groups=groups))


def _zone(name: str):
    try:
        return ZoneInfo(name) if name else dt_util.get_default_time_zone()
    except (ZoneInfoNotFoundError, ValueError):
        return dt_util.get_default_time_zone()
