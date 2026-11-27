"""End-to-end tests against a real HA core and the fake dongle (TCP on localhost)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

pytest.importorskip("pytest_homeassistant_custom_component")

from homeassistant import config_entries, loader
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.kessil_dongle.const import DOMAIN

LIGHT = "light.kessil_a360x_tuna_sun"
MODE = "select.kessil_a360x_tuna_sun_mode"
PREFIX = "kessil_a360x_tuna_sun"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture(autouse=True)
def no_frontend():
    """Skip the frontend/http stack (not installed in tests) and the card setup."""

    def deps(self):
        return [] if self.domain == DOMAIN else self.manifest.get("dependencies", [])

    with (
        patch.object(loader.Integration, "dependencies", property(deps)),
        patch("custom_components.kessil_dongle.async_setup", return_value=True),
    ):
        yield


# 14:00 in the dongle's time zone (Europe/Berlin) = point 840 of program "Default":
# UI [204, 255, 0, 30, 0]. The group's stored manual UI is [128, 117, 0, 78, 56].
NOON = "2026-11-27 13:00:00+00:00"


@pytest.fixture(autouse=True)
def fixed_time(freezer):
    freezer.move_to(NOON)


async def setup(hass: HomeAssistant, fake) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="DONGLE0001",
        data={CONF_HOST: "127.0.0.1", CONF_PORT: fake.port},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_entities_created(hass: HomeAssistant, fake) -> None:
    async with fake:
        entry = await setup(hass, fake)

        light = hass.states.get(LIGHT)
        assert light.state == "on"
        assert light.attributes["brightness"] == 204  # from the curve, not the stored UI
        assert light.attributes["manual"] is False

        assert hass.states.get(f"number.{PREFIX}_color").state == "100"
        assert hass.states.get(f"number.{PREFIX}_red").state == "30"
        assert hass.states.get(f"number.{PREFIX}_amber").state == "0"

        mode = hass.states.get(MODE)
        assert mode.state == "Default"
        assert mode.attributes["options"] == ["manual", "Preset Tuna Sun", "Default"]
        assert len(mode.attributes["programs"]["Default"]) == 12

        assert hass.states.get(f"sensor.{PREFIX}_lamps").state == "2"

        overheat = hass.states.get(f"sensor.{PREFIX}_overheat_status_lamp_1")
        assert overheat.state == "0"
        assert overheat.attributes["lamp_id"] == 10000001
        assert overheat.attributes["firmware"] == "1.3"
        assert hass.states.get(f"sensor.{PREFIX}_overheat_status_lamp_2") is not None

        devices = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
        assert len(devices) == 1
        assert devices[0].name == "Kessil A360X Tuna Sun"
        assert devices[0].model == "A360X Tuna Sun"


async def test_old_devices_removed(hass: HomeAssistant, fake) -> None:
    async with fake:
        entry = MockConfigEntry(
            domain=DOMAIN,
            unique_id="DONGLE0001",
            data={CONF_HOST: "127.0.0.1", CONF_PORT: fake.port},
        )
        entry.add_to_hass(hass)
        registry = dr.async_get(hass)
        for ident in ("DONGLE0001", "lamp_10000001", "lamp_10000002"):
            registry.async_get_or_create(
                config_entry_id=entry.entry_id, identifiers={(DOMAIN, ident)}
            )
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        devices = dr.async_entries_for_config_entry(registry, entry.entry_id)
        assert [d.name for d in devices] == ["Kessil A360X Tuna Sun"]


async def test_turn_off_switches_to_manual(hass: HomeAssistant, fake) -> None:
    async with fake:
        await setup(hass, fake)
        fake.requests.clear()

        await hass.services.async_call("light", "turn_off", {"entity_id": LIGHT}, blocking=True)

        assert fake.requests == [
            {"dtype": 100, "data": {"GID": 2, "PID": 0}},
            {
                "dtype": 3,
                "data": {
                    "GID": 2,
                    "UI1": 0,
                    "UI2": 255,
                    "UI3": 0,
                    "UI4": 30,
                    "UI5": 0,
                    "save": 1,
                    "enabled": 1,
                },
            },
        ]
        assert hass.states.get(LIGHT).state == "off"
        assert hass.states.get(MODE).state == "manual"

        # Turning on again restores the last brightness, no second mode switch.
        fake.requests.clear()
        await hass.services.async_call("light", "turn_on", {"entity_id": LIGHT}, blocking=True)
        assert [r["dtype"] for r in fake.requests] == [3]
        assert fake.requests[0]["data"]["UI1"] == 204


async def test_set_number(hass: HomeAssistant, fake) -> None:
    async with fake:
        await setup(hass, fake)
        fake.requests.clear()
        await hass.services.async_call(
            "number",
            "set_value",
            {"entity_id": f"number.{PREFIX}_red", "value": 50},
            blocking=True,
        )
        assert fake.requests[-1]["data"]["UI4"] == 50  # red/amber are 0-100 raw
        assert fake.requests[-1]["data"]["UI1"] == 204


async def test_select_program(hass: HomeAssistant, fake) -> None:
    async with fake:
        await setup(hass, fake)
        fake.requests.clear()
        await hass.services.async_call(
            "select",
            "select_option",
            {"entity_id": MODE, "option": "Preset Tuna Sun"},
            blocking=True,
        )
        assert fake.requests[0] == {"dtype": 100, "data": {"GID": 2, "PID": 1}}
        assert fake.requests[1]["dtype"] == 102


async def test_setup_retry_when_unreachable(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id="X", data={CONF_HOST: "127.0.0.1", CONF_PORT: 1}
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is config_entries.ConfigEntryState.SETUP_RETRY


async def test_config_flow(hass: HomeAssistant, fake) -> None:
    async with fake:
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        assert result["type"] is FlowResultType.FORM

        bad = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_HOST: "127.0.0.1", CONF_PORT: 1}
        )
        assert bad["errors"] == {"base": "cannot_connect"}

        with patch("custom_components.kessil_dongle.async_setup_entry", return_value=True):
            ok = await hass.config_entries.flow.async_configure(
                result["flow_id"], {CONF_HOST: "127.0.0.1", CONF_PORT: fake.port}
            )
        assert ok["type"] is FlowResultType.CREATE_ENTRY
        assert ok["result"].unique_id == "DONGLE0001"


async def test_program_night_shows_off(hass: HomeAssistant, fake, freezer) -> None:
    freezer.move_to("2026-11-27 19:00:00+00:00")  # 20:00 Berlin, after the curve's end
    async with fake:
        await setup(hass, fake)
        assert hass.states.get(LIGHT).state == "off"
        assert hass.states.get(MODE).state == "Default"
