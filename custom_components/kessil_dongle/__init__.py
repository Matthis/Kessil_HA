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
    """Dongle → groups → lamps, registered in order so via_device resolves."""
    registry = dr.async_get(hass)
    system = coordinator.data.system
    hub = (DOMAIN, system.serial)
    registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={hub},
        manufacturer=MANUFACTURER,
        model="WiFi Dongle",
        name="Kessil WiFi Dongle",
        serial_number=system.serial,
        sw_version=system.firmware,
        configuration_url=None,
    )
    for group in coordinator.data.groups.values():
        registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={group_identifier(system.serial, group.gid)},
            manufacturer=MANUFACTURER,
            model=f"Lamp group ({TYPE_NAMES.get(group.type, group.type)})",
            name=group.name or f"Kessil group {group.gid}",
            via_device=hub,
        )
    for lamp in system.lamps:
        registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, f"lamp_{lamp.kid}")},
            manufacturer=MANUFACTURER,
            model=lamp.model,
            name=f"{lamp.model} {lamp.kid}",
            serial_number=str(lamp.kid),
            sw_version=lamp.firmware,
            via_device=group_identifier(system.serial, lamp.gid),
        )


def group_identifier(serial: str, gid: int) -> tuple[str, str]:
    return (DOMAIN, f"{serial}_group_{gid}")
