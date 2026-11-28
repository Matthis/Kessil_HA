"""Actions for managing the programs stored in the dongle."""

from __future__ import annotations

import re
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er

from .api import TYPE_NAMES, Group, is_preset
from .const import DOMAIN
from .coordinator import KessilCoordinator

ATTR_NAME = "name"
ATTR_NEW_NAME = "new_name"
ATTR_POINTS = "points"
ATTR_PROGRAM = "program"

SERVICE_EXPORT = "export_programs"
SERVICE_SAVE = "save_program"
SERVICE_RENAME = "rename_program"
SERVICE_DELETE = "delete_program"

_GROUP_RE = re.compile(r"_group_(\d+)_")

BASE = {vol.Required(ATTR_ENTITY_ID): cv.entity_id}
SCHEMAS = {
    SERVICE_EXPORT: vol.Schema(BASE),
    SERVICE_SAVE: vol.Schema(
        {
            **BASE,
            vol.Required(ATTR_NAME): cv.string,
            vol.Required(ATTR_POINTS): vol.All(cv.ensure_list, [dict]),
        }
    ),
    SERVICE_RENAME: vol.Schema(
        {**BASE, vol.Required(ATTR_PROGRAM): cv.string, vol.Required(ATTR_NEW_NAME): cv.string}
    ),
    SERVICE_DELETE: vol.Schema({**BASE, vol.Required(ATTR_PROGRAM): cv.string}),
}


def async_setup_services(hass: HomeAssistant) -> None:
    hass.services.async_register(
        DOMAIN,
        SERVICE_EXPORT,
        _export,
        schema=SCHEMAS[SERVICE_EXPORT],
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SAVE,
        _save,
        schema=SCHEMAS[SERVICE_SAVE],
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(DOMAIN, SERVICE_RENAME, _rename, schema=SCHEMAS[SERVICE_RENAME])
    hass.services.async_register(DOMAIN, SERVICE_DELETE, _delete, schema=SCHEMAS[SERVICE_DELETE])


def _target(call: ServiceCall) -> tuple[KessilCoordinator, Group]:
    """Coordinator and lamp group behind any entity of this integration."""
    entity_id = call.data[ATTR_ENTITY_ID]
    entry = er.async_get(call.hass).async_get(entity_id)
    match = _GROUP_RE.search(entry.unique_id) if entry and entry.platform == DOMAIN else None
    config_entry = (
        call.hass.config_entries.async_get_entry(entry.config_entry_id) if match else None
    )
    if config_entry is None or config_entry.state is not ConfigEntryState.LOADED:
        raise ServiceValidationError(f"{entity_id} is not an entity of a Kessil lamp group")
    coordinator: KessilCoordinator = config_entry.runtime_data
    group = coordinator.data.groups.get(int(match.group(1)))
    if group is None:
        raise ServiceValidationError(f"The lamp group of {entity_id} is not available")
    return coordinator, group


async def _export(call: ServiceCall) -> ServiceResponse:
    coordinator, group = _target(call)
    return {
        "lamp_type": TYPE_NAMES.get(group.type, str(group.type)),
        "type": group.type,
        "programs": [
            {
                "name": program.name,
                "pid": program.pid,
                "preset": is_preset(group.type, program.pid),
                "points": [p.to_json() for p in program.points],
            }
            for program in coordinator.data.programs_for(group)
        ],
    }


async def _save(call: ServiceCall) -> ServiceResponse:
    coordinator, group = _target(call)
    program = await coordinator.async_save_program(
        group.type, call.data[ATTR_NAME], call.data[ATTR_POINTS]
    )
    result: dict[str, Any] = {"name": program.name, "pid": program.pid}
    return result if call.return_response else None


async def _rename(call: ServiceCall) -> None:
    coordinator, group = _target(call)
    await coordinator.async_rename_program(
        group.type, call.data[ATTR_PROGRAM], call.data[ATTR_NEW_NAME]
    )


async def _delete(call: ServiceCall) -> None:
    coordinator, group = _target(call)
    await coordinator.async_delete_program(group.type, call.data[ATTR_PROGRAM])
