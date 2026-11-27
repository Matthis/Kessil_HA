"""Unofficial Home Assistant integration for the Kessil WiFi dongle."""

from __future__ import annotations

from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.const import CONF_HOST, CONF_PORT, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.typing import ConfigType

from .api import DEFAULT_PORT, TYPE_NAMES, KessilDongle
from .const import CARD_URL, DOMAIN, MANUFACTURER
from .coordinator import KessilConfigEntry, KessilCoordinator

PLATFORMS: list[Platform] = [
    Platform.LIGHT,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

CARD_FILE = Path(__file__).parent / "frontend" / "kessil-card.js"


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Serve the bundled Lovelace card and load it in the frontend."""
    await hass.http.async_register_static_paths([StaticPathConfig(CARD_URL, str(CARD_FILE), True)])
    version = await hass.async_add_executor_job(lambda: int(CARD_FILE.stat().st_mtime))
    add_extra_js_url(hass, f"{CARD_URL}?v={version}")
    return True


async def async_setup_entry(hass: HomeAssistant, entry: KessilConfigEntry) -> bool:
    client = KessilDongle(entry.data[CONF_HOST], entry.data.get(CONF_PORT, DEFAULT_PORT))
    coordinator = KessilCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    _register_devices(hass, entry, coordinator)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: KessilConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


def _register_devices(
    hass: HomeAssistant, entry: KessilConfigEntry, coordinator: KessilCoordinator
) -> None:
    """One device per lamp group; the dongle and single lamps are not devices.

    Devices left over from earlier versions (dongle hub, one device per lamp)
    are removed from this config entry.
    """
    registry = dr.async_get(hass)
    system = coordinator.data.system
    names = group_device_names(coordinator)
    keep: set[str] = set()
    for group in coordinator.data.groups.values():
        lamps = [lamp for lamp in system.lamps if lamp.gid == group.gid]
        models = sorted({lamp.model for lamp in lamps})
        device = registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={group_identifier(system.serial, group.gid)},
            manufacturer=MANUFACTURER,
            model=" / ".join(models) or TYPE_NAMES.get(group.type, "Lamp group"),
            name=names[group.gid],
            sw_version=f"Dongle {system.firmware}",
            serial_number=system.serial,
        )
        keep.add(device.id)
    for device in dr.async_entries_for_config_entry(registry, entry.entry_id):
        if device.id not in keep:
            registry.async_update_device(device.id, remove_config_entry_id=entry.entry_id)


def group_device_names(coordinator: KessilCoordinator) -> dict[int, str]:
    """ "Kessil Group - <type>" as in the Kessil app, plus the dongle's group name
    if that is ambiguous."""
    groups = coordinator.data.groups
    base = {
        gid: f"Kessil Group - {TYPE_NAMES.get(group.type, group.type)}"
        for gid, group in groups.items()
    }
    counts = {name: list(base.values()).count(name) for name in base.values()}
    return {
        gid: f"{name} ({groups[gid].name})" if counts[name] > 1 else name
        for gid, name in base.items()
    }


def group_identifier(serial: str, gid: int) -> tuple[str, str]:
    return (DOMAIN, f"{serial}_group_{gid}")
