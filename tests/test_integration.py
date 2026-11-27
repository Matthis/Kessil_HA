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

LIGHT = "light.kessil_group_tuna_sun"
MODE = "select.kessil_group_tuna_sun_mode"
PREFIX = "kessil_group_tuna_sun"


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

        assert hass.states.get(f"number.{PREFIX}_intensity").state == "80"
        assert hass.states.get(f"number.{PREFIX}_color_temperature").state == "100"
        assert hass.states.get(f"number.{PREFIX}_red").state == "30"
        assert hass.states.get(f"number.{PREFIX}_amber").state == "0"

        mode = hass.states.get(MODE)
        assert mode.state == "Default"
        assert mode.attributes["options"] == ["manual", "Preset Tuna Sun", "Default"]
        points = mode.attributes["programs"]["Default"]
        assert len(points) == 12
        assert [p[0] for p in points if p[6] >= 0] == [720]  # thunderstorm at 12:00

        assert hass.states.get(f"sensor.{PREFIX}_lamps").state == "2"

        overheat = hass.states.get(f"sensor.{PREFIX}_overheat_status_lamp_1")
        assert overheat.state == "0"
        assert overheat.attributes["lamp_id"] == 10000001
        assert overheat.attributes["firmware"] == "1.3"
        assert hass.states.get(f"sensor.{PREFIX}_overheat_status_lamp_2") is not None

        devices = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
        assert len(devices) == 1
        assert devices[0].name == "Kessil Group - Tuna Sun"
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
        assert [d.name for d in devices] == ["Kessil Group - Tuna Sun"]


def _ui(request: dict) -> list[int]:
    return [request["data"][f"UI{i}"] for i in range(1, 6)]


async def test_turn_off_switches_to_manual(hass: HomeAssistant, fake) -> None:
    async with fake:
        await setup(hass, fake)
        fake.requests.clear()

        await hass.services.async_call("light", "turn_off", {"entity_id": LIGHT}, blocking=True)

        # Base is the dongle's stored manual UI [128, 117, 0, 78, 56];
        # off zeroes intensity, red and amber (separate LEDs).
        assert fake.requests[0] == {"dtype": 100, "data": {"GID": 2, "PID": 0}}
        assert fake.requests[1]["dtype"] == 3
        assert _ui(fake.requests[1]) == [0, 117, 0, 0, 0]
        assert hass.states.get(LIGHT).state == "off"
        assert hass.states.get(MODE).state == "manual"


def _manual(fake, ui: str) -> None:
    fake.responses[(102, 2)] = (
        fake.responses[(102, 2)]
        .replace('"pid":3', '"pid":-1')
        .replace('"UI":[128,117,0,78,56]', f'"UI":{ui}')
    )


async def test_turn_on_manual_off_uses_default_intensity(hass: HomeAssistant, fake) -> None:
    _manual(fake, "[0,117,0,0,0]")
    async with fake:
        await setup(hass, fake)
        assert hass.states.get(LIGHT).state == "off"
        fake.requests.clear()
        await hass.services.async_call("light", "turn_on", {"entity_id": LIGHT}, blocking=True)
        assert [r["dtype"] for r in fake.requests] == [3]  # already manual
        assert _ui(fake.requests[0]) == [128, 117, 0, 0, 0]
        assert hass.states.get(LIGHT).state == "on"


async def test_turn_on_with_brightness(hass: HomeAssistant, fake) -> None:
    _manual(fake, "[0,117,0,0,0]")
    async with fake:
        await setup(hass, fake)
        fake.requests.clear()
        await hass.services.async_call(
            "light", "turn_on", {"entity_id": LIGHT, "brightness": 100}, blocking=True
        )
        assert _ui(fake.requests[-1]) == [100, 117, 0, 0, 0]


async def test_turn_on_while_program_lit_does_nothing(hass: HomeAssistant, fake) -> None:
    async with fake:
        await setup(hass, fake)
        fake.requests.clear()
        await hass.services.async_call("light", "turn_on", {"entity_id": LIGHT}, blocking=True)
        assert fake.requests == []


async def test_set_number(hass: HomeAssistant, fake) -> None:
    async with fake:
        await setup(hass, fake)
        fake.requests.clear()
        await hass.services.async_call(
            "number", "set_value", {"entity_id": f"number.{PREFIX}_red", "value": 50}, blocking=True
        )
        assert _ui(fake.requests[-1]) == [128, 117, 0, 50, 56]  # red 0-100 raw


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


async def test_select_manual_applies_stored_values(hass: HomeAssistant, fake) -> None:
    async with fake:
        await setup(hass, fake)
        fake.requests.clear()
        await hass.services.async_call(
            "select", "select_option", {"entity_id": MODE, "option": "manual"}, blocking=True
        )
        assert fake.requests[0] == {"dtype": 100, "data": {"GID": 2, "PID": 0}}
        assert fake.requests[1]["dtype"] == 3
        assert _ui(fake.requests[1]) == [128, 117, 0, 78, 56]
        assert hass.states.get(MODE).state == "manual"


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


async def test_program_counts_as_on_at_night(hass: HomeAssistant, fake, freezer) -> None:
    freezer.move_to("2026-11-27 19:00:00+00:00")  # 20:00 Berlin, after the curve's end
    async with fake:
        await setup(hass, fake)
        light = hass.states.get(LIGHT)
        assert light.state == "on"  # operating state: program runs
        assert light.attributes["brightness"] == 0
        assert hass.states.get(MODE).state == "Default"


async def test_red_only_counts_as_on(hass: HomeAssistant, fake) -> None:
    fake.responses[(102, 2)] = (
        fake.responses[(102, 2)]
        .replace('"pid":3', '"pid":-1')
        .replace('"UI":[128,117,0,78,56]', '"UI":[0,117,0,40,0]')
    )
    async with fake:
        await setup(hass, fake)
        assert hass.states.get(LIGHT).state == "on"
        fake.requests.clear()
        await hass.services.async_call("light", "turn_off", {"entity_id": LIGHT}, blocking=True)
        data = fake.requests[-1]["data"]
        assert [data[f"UI{i}"] for i in range(1, 6)] == [0, 117, 0, 0, 0]
        assert hass.states.get(LIGHT).state == "off"
