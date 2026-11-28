"""Protocol client tests against the fake dongle (TCP on localhost)."""

from __future__ import annotations

import asyncio

import pytest
from conftest import api


def client(fake, **kw):
    return api.KessilDongle("127.0.0.1", fake.port, **kw)


async def test_serial(fake):
    async with fake:
        assert await client(fake).get_serial() == "DONGLE0001"
    assert fake.requests == [{"dtype": 117, "data": {}}]


async def test_system_info(fake):
    async with fake:
        info = await client(fake).get_system_info()
    assert info.serial == "DONGLE0001"
    assert info.firmware == "1.5.13"
    assert info.timezone == "Europe/Berlin"
    assert info.group_ids == (1, 2, 26, 27)
    assert info.program_ids["TS"] == (0, 1, 3)
    assert [lamp.kid for lamp in info.lamps] == [10000001, 10000002]
    assert {lamp.firmware for lamp in info.lamps} == {"1.3", "1.5"}


async def test_lamps_multiline_response(fake):
    async with fake:
        lamps = await client(fake).get_lamps()
    assert len(lamps) == 2
    assert lamps[0] == api.Lamp(
        kid=10000001, gid=2, model="A360X Tuna Sun", firmware="1.3", type=2, temp=0
    )


async def test_group(fake):
    async with fake:
        group = await client(fake).get_group(2)
    assert group.gid == 2
    assert group.pid == 3
    assert not group.is_manual
    assert group.type_key == "TS"
    assert group.lamp_count == 2
    assert len(group.ui) == 5
    assert fake.requests[0] == {"dtype": 102, "data": {"GID": 2}}


async def test_program_ids(fake):
    async with fake:
        ids = await client(fake).get_program_ids()
    assert ids == {"TB": (0, 1), "TS": (0, 1, 3), "RF": (0, 1, 2), "Z2T": (0, 1)}


async def test_program(fake):
    async with fake:
        program = await client(fake).get_program(3, 2)
    assert program.pid == 3
    assert program.name == "Default"
    assert len(program.points) == 12
    assert program.points[0].minutes == 449
    minutes = [p.minutes for p in program.points]
    assert minutes == sorted(minutes)
    assert all(len(p.ui) == 5 for p in program.points)
    storms = [p for p in program.points if p.effect == 0]
    assert [(p.minutes, p.duration) for p in storms] == [(720, 300)]


async def test_program_pid0_is_error(fake):
    async with fake:
        with pytest.raises(api.KessilCommandError) as exc:
            await client(fake).get_program(0, 2)
    assert exc.value.code == -1


async def test_unknown_command_raises(fake):
    async with fake:
        with pytest.raises(api.KessilCommandError):
            await client(fake).request(325)


async def test_chunked_response(fake):
    fake.chunk_size = 7
    async with fake:
        program = await client(fake).get_program(3, 2)
    assert len(program.points) == 12


async def test_timeout(fake):
    fake.silent = True
    async with fake:
        with pytest.raises(api.KessilConnectionError):
            await client(fake, timeout=0.3).get_serial()


async def test_connection_refused():
    with pytest.raises(api.KessilConnectionError):
        await api.KessilDongle("127.0.0.1", 1, timeout=1).get_serial()


async def test_run_program_payload(fake):
    async with fake:
        await client(fake).run_program(2, 0)
    assert fake.requests == [{"dtype": 100, "data": {"GID": 2, "PID": 0}}]


async def test_set_manual_payload_clamps(fake):
    async with fake:
        await client(fake).set_manual(2, [300, 117, 0, 78, -5])
    assert fake.requests == [
        {
            "dtype": 3,
            "data": {
                "GID": 2,
                "UI1": 255,
                "UI2": 117,
                "UI3": 0,
                "UI4": 78,
                "UI5": 0,
                "save": 1,
                "enabled": 1,
            },
        }
    ]


async def test_set_manual_requires_five_channels():
    with pytest.raises(ValueError):
        await api.KessilDongle("127.0.0.1").set_manual(2, [1, 2, 3])


async def test_commands_are_serialized(fake):
    fake.delay = 0.05
    async with fake:
        c = client(fake)
        await asyncio.gather(*(c.get_serial() for _ in range(5)))
    assert len(fake.requests) == 5
    assert fake.max_active == 1


def _program(points):
    return api.Program(
        pid=9,
        type=2,
        name="t",
        points=tuple(api.ProgramPoint(m, tuple(ui)) for m, ui in points),
    )


def test_value_at_exact_and_between():
    p = _program([(600, [0, 0, 0, 0, 0]), (720, [200, 100, 0, 20, 40])])
    assert p.value_at(600) == (0, 0, 0, 0, 0)
    assert p.value_at(720) == (200, 100, 0, 20, 40)
    assert p.value_at(660) == (100, 50, 0, 10, 20)


def test_value_at_wraps_midnight():
    p = _program([(480, [0, 0, 0, 0, 0]), (1200, [240, 0, 0, 0, 0])])
    # 1200 -> 480 next day = 720 min; midnight is 240 min (1/3) in -> 240 * 2/3
    assert p.value_at(0) == (160, 0, 0, 0, 0)
    assert p.value_at(1439.99)[0] == 160


def test_value_at_real_program(fake):
    import json

    from conftest import fixture_text

    program = api.Program.from_json(json.loads(fixture_text("106_pid3"))["program"])
    assert program.value_at(840) == (204, 255, 0, 30, 0)
    assert program.value_at(20 * 60) == (0, 0, 0, 0, 0)
    assert program.value_at(3 * 60) == (0, 0, 0, 0, 0)


# --- program editing ---------------------------------------------------------

NATURAL_DAY = [
    {"minutes": 480, "UI": [0, 0, 0, 0, 0]},
    {"minutes": 815, "UI": [36, 93, 0, 6, 0], "eid": 0, "duration": 300, "freq": 0},
    {"minutes": 720, "UI": [200, 150, 0, 10, 0]},
    {"minutes": 1140, "UI": [0, 0, 0, 0, 0]},
]


def test_parse_points_sorts_and_fills_defaults():
    points = api.parse_points(NATURAL_DAY, 2)
    assert [p.minutes for p in points] == [480, 720, 815, 1140]
    assert points[2] == api.ProgramPoint(815, (36, 93, 0, 6, 0), 0, 300, 0)
    assert points[0] == api.ProgramPoint(480, (0, 0, 0, 0, 0), -1, 30, 1)


def test_parse_points_short_ui_is_padded():
    points = api.parse_points([{"minutes": 0, "UI": [0]}, {"minutes": 60, "UI": [9, 9]}], 1)
    assert points[1].ui == (9, 9, 0, 0, 0)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda pts: pts[:1], "at least 2 points"),
        (lambda pts: [{"minutes": i, "UI": [0] * 5} for i in range(21)], "at most 20 points"),
        (lambda pts: [*pts, {"minutes": 600, "UI": [10, 0, 0, 101, 0]}], "channel 4 must be 0-100"),
        (lambda pts: [*pts, {"minutes": 600, "UI": [256, 0, 0, 0, 0]}], "channel 1 must be 0-255"),
        (lambda pts: [*pts, {"minutes": 1440, "UI": [0] * 5}], "minutes must be"),
        (lambda pts: [*pts, {"minutes": 480, "UI": [5] * 5}], "same time"),
        (lambda pts: [{**p, "UI": [1, 0, 0, 0, 0]} for p in pts], "intensity 0"),
        (lambda pts: [*pts, {"minutes": 600, "UI": [9] * 5, "eid": 2}], "effect 2"),
        (lambda pts: [*pts, {"minutes": 600, "UI": [9] * 5, "eid": 0, "duration": 45}], "duration"),
        (lambda pts: [*pts, {"minutes": 600, "UI": [9] * 5, "eid": 1, "freq": 3}], "frequency"),
        (lambda pts: [*pts, {"minutes": 600}], "'UI'"),
    ],
)
def test_parse_points_rejects(change, message):
    with pytest.raises(ValueError, match=message):
        api.parse_points(change(NATURAL_DAY), 2)


def test_rainbow_only_for_tuna_blue():
    pts = [*NATURAL_DAY, {"minutes": 600, "UI": [9] * 5, "eid": 2}]
    assert api.parse_points(pts, 1)[1].effect == 2


def test_validate_name():
    assert api.validate_name("  Natural Day ") == "Natural Day"
    assert api.validate_name("x" * 31) == "x" * 31
    for bad in ("", "   ", "x" * 32, "ä" * 16):  # umlauts take two bytes
        with pytest.raises(ValueError):
            api.validate_name(bad)


def test_presets():
    assert api.is_preset(2, 1)
    assert not api.is_preset(2, 3)
    assert api.is_preset(3, 2)  # Refugium "Daylight Mode"


async def test_save_program_sends_upper_case_eid(fake):
    fake.responses[(107, None)] = '{"msg":"Success","code":0,"dType":107}'
    program = api.Program(
        pid=2, type=2, name="Natural Day", points=api.parse_points(NATURAL_DAY, 2)
    )
    async with fake:
        await client(fake).save_program(program)
    data = fake.requests[-1]["data"]
    assert (data["PID"], data["type"], data["name"]) == (2, 2, "Natural Day")
    storm = data["points"][2]
    assert storm == {"minutes": 815, "UI": [36, 93, 0, 6, 0], "EID": 0, "duration": 300, "freq": 0}
    assert all("eid" not in p for p in data["points"])


async def test_save_program_refuses_long_name(fake):
    program = api.Program(pid=2, type=2, name="N" * 64, points=api.parse_points(NATURAL_DAY, 2))
    async with fake:
        with pytest.raises(ValueError):
            await client(fake).save_program(program)
    assert fake.requests == []


async def test_rename_delete_move(fake):
    for dtype in (108, 109, 110):
        fake.responses[(dtype, None)] = f'{{"msg":"Success","code":0,"dType":{dtype}}}'
    async with fake:
        c = client(fake)
        await c.rename_program(4, 2, "Renamed")
        await c.delete_program(4, 2)
        await c.move_program(1, 2, 3)
    assert [(r["dtype"], r["data"]) for r in fake.requests] == [
        (110, {"PID": 4, "type": 2, "name": "Renamed"}),
        (108, {"PID": 4, "type": 2}),
        (109, {"from": 1, "to": 2, "type": 3}),
    ]
