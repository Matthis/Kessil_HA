"""Generate the "Natural Day" example program (programs/natural_day.json).

Daily light amounts are taken from a reference program (a dtype 106 response):
each channel is scaled so its daily amount matches the reference. The day runs
from DAY_START to DAY_END (see ANCHORS for how the template is placed).

Usage: python scripts/natural_day.py tests/fixtures/dtype_106_pid3.json programs
"""

import json
import sys
from itertools import pairwise
from pathlib import Path

DAY_START, DAY_END = "08:00", "19:00"

# Relative shape on a 07:30-17:00 template day.
# (hh:mm, intensity 0-1, color temperature 0-1, red 0-1, amber 0-1, thunderstorm)
SHAPE = [
    ("07:30", 0.00, 0.00, 0.00, 0.00, False),  # night
    ("07:40", 0.00, 0.00, 0.10, 0.25, False),  # first glow
    ("07:55", 0.01, 0.00, 0.45, 0.70, False),  # dawn: amber/red rise
    ("08:10", 0.06, 0.00, 0.80, 1.00, False),  # sunrise: deep orange
    ("08:25", 0.18, 0.15, 0.70, 0.75, False),
    ("08:45", 0.40, 0.40, 0.45, 0.35, False),  # morning, warm white
    ("09:15", 0.65, 0.70, 0.20, 0.10, False),
    ("10:00", 0.86, 0.85, 0.10, 0.00, False),
    ("11:30", 0.97, 0.95, 0.10, 0.00, False),
    ("13:05", 1.00, 1.00, 0.10, 0.00, False),  # zenith
    ("13:10", 0.18, 0.60, 0.10, 0.00, True),  # thunderstorm (dongle effect, 5 min after zenith)
    ("13:20", 0.98, 0.95, 0.10, 0.00, False),  # clears up
    ("14:30", 0.90, 0.85, 0.12, 0.00, False),
    ("15:30", 0.70, 0.55, 0.25, 0.15, False),  # afternoon, warmer
    ("16:10", 0.38, 0.25, 0.55, 0.50, False),
    ("16:30", 0.12, 0.05, 0.85, 1.00, False),  # sunset glow
    ("16:45", 0.02, 0.00, 0.55, 0.60, False),
    ("16:55", 0.00, 0.00, 0.15, 0.20, False),  # dusk
    ("17:00", 0.00, 0.00, 0.00, 0.00, False),  # night
]
# channel index -> maximum raw value accepted by the dongle
CAPS = {0: 255, 1: 255, 3: 100, 4: 100}
NAMES = {0: "Intensity", 1: "Color temp.", 3: "Red", 4: "Amber"}


def minutes(hhmm: str) -> int:
    hours, mins = map(int, hhmm.split(":"))
    return hours * 60 + mins


# Template time -> target time anchors; times in between are interpolated linearly
# (rounded to 5 minutes). Sunrise and sunset keep their length, the zenith
# (and the storm right after it) moves to the middle of the day.
ANCHORS = [
    ("07:30", DAY_START),
    ("08:45", "+75"),  # end of sunrise: 75 min after the start
    ("13:05", "mid"),  # zenith
    ("16:10", "-50"),  # start of sunset: 50 min before the end
    ("17:00", DAY_END),
]


def place(hhmm: str) -> int:
    """Map a template time to the configured day (minutes after midnight)."""
    start, end = minutes(DAY_START), minutes(DAY_END)

    def target(spec: str) -> int:
        if spec == "mid":
            return (start + end) // 2
        if spec[0] in "+-":
            return (start if spec[0] == "+" else end) + int(spec)
        return minutes(spec)

    anchors = [(minutes(a), target(b)) for a, b in ANCHORS]
    t = minutes(hhmm)
    for (a0, b0), (a1, b1) in pairwise(anchors):
        if a0 <= t <= a1:
            exact = b0 + (t - a0) * (b1 - b0) / (a1 - a0)
            return round(exact) if t in (a0, a1) else round(exact / 5) * 5
    raise ValueError(hhmm)


def integral(points: list[dict], ch: int) -> float:
    """Daily amount of a channel (raw value x minutes, linear between points)."""
    pts = sorted(points, key=lambda p: p["minutes"])
    return sum(
        (b["minutes"] - a["minutes"]) * (a["UI"][ch] + b["UI"][ch]) / 2 for a, b in pairwise(pts)
    )


def build(reference: list[dict]) -> dict:
    relative = []
    for t, i, c, r, a, storm in SHAPE:
        # keep the storm's distance to the point before it, and the clearing after it
        at = relative[-1]["minutes"] + 5 if storm else place(t)
        if relative and SHAPE[len(relative) - 1][5]:
            at = relative[-1]["minutes"] + 10
        relative.append({"minutes": at, "UI": [i, c, 0, r, a]})
    scale = {
        ch: min(
            integral(reference, ch) / integral(relative, ch),
            cap / max(p["UI"][ch] for p in relative),
        )
        for ch, cap in CAPS.items()
    }
    points = []
    prev_storm = False
    for row, rel in zip(SHAPE, relative, strict=True):
        storm = row[5]
        slow = storm or prev_storm  # Default uses duration 300 / freq 0 around the storm
        points.append(
            {
                "minutes": rel["minutes"],
                "UI": [round(rel["UI"][ch] * scale[ch]) if ch in scale else 0 for ch in range(5)],
                "eid": 0 if storm else -1,
                "duration": 300 if slow else 30,
                "freq": 0 if slow else 1,
            }
        )
        prev_storm = storm
    return {"name": "Natural Day", "type": 2, "points": points}


def main() -> None:
    reference = json.loads(Path(sys.argv[1]).read_text())["program"]["points"]
    program = build(reference)
    Path(sys.argv[2], "natural_day.json").write_text(json.dumps(program, indent=1) + "\n")

    print(f"{len(program['points'])} points")
    for ch in CAPS:
        ref, new = integral(reference, ch), integral(program["points"], ch)
        print(
            f"{NAMES[ch]:11} reference {ref:7.0f} | Natural Day {new:7.0f} ({(new / ref - 1):+.1%})"
        )
    for p in program["points"]:
        i, c, _, r, a = p["UI"]
        time = f"{p['minutes'] // 60:02d}:{p['minutes'] % 60:02d}"
        storm = "  thunderstorm" if p["eid"] == 0 else ""
        print(f"  {time}  I={i:3d} CT={c:3d} R={r:3d} A={a:3d}{storm}")


if __name__ == "__main__":
    main()
