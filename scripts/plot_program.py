"""Plot a program file (dongle program format) as a daily curve.

Usage: python scripts/plot_program.py <program.json> <out.png>
Requires Pillow.
"""

import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, PANEL_H, LEFT, RIGHT, TOP = 1400, 330, 70, 30, 50
START, END = 7 * 60, 20 * 60  # visible time window in minutes
SERIES = [  # channel, max raw value, color, label, line width
    (0, 255, (79, 195, 247), "Intensity", 4),
    (1, 255, (190, 170, 120), "Color temperature", 2),
    (3, 100, (229, 57, 53), "Red (0-100)", 2),
    (4, 100, (245, 118, 26), "Amber (0-100)", 2),
]


def load_font(size: int):
    try:
        return ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", size)
    except OSError:
        return ImageFont.load_default()


def x_pos(minute: float) -> float:
    return LEFT + (minute - START) / (END - START) * (W - LEFT - RIGHT)


def draw_panel(draw, top: int, points: list[dict], title: str, font, small) -> None:
    pts = sorted(points, key=lambda p: p["minutes"])

    def y_pos(value: float, cap: int) -> float:
        return top + TOP + (1 - value / cap) * (PANEL_H - TOP - 40)

    draw.text((LEFT, top + 10), title, fill="black", font=font)
    for hour in range(7, 21):
        x = x_pos(hour * 60)
        draw.line([(x, top + TOP), (x, top + PANEL_H - 40)], fill=(235, 235, 235))
        draw.text((x - 12, top + PANEL_H - 32), f"{hour}:00", fill=(110, 110, 110), font=small)
    for ch, cap, color, _, width in SERIES:
        line = [(x_pos(START), y_pos(0, cap))]
        line += [
            (x_pos(p["minutes"]), y_pos(p["UI"][ch], cap))
            for p in pts
            if START <= p["minutes"] <= END
        ]
        line += [(x_pos(END), y_pos(0, cap))]
        draw.line(line, fill=color, width=width)
    for p in pts:
        if p.get("eid", -1) >= 0:
            draw.text(
                (x_pos(p["minutes"]) - 40, top + TOP - 22),
                "Thunderstorm",
                fill=(200, 150, 0),
                font=small,
            )


def main() -> None:
    program = json.loads(Path(sys.argv[1]).read_text())
    img = Image.new("RGB", (W, PANEL_H + 70), "white")
    draw = ImageDraw.Draw(img)
    font, small = load_font(20), load_font(16)
    draw_panel(draw, 0, program["points"], program["name"], font, small)
    legend_x = LEFT
    for _, _, color, label, _ in SERIES:
        draw.rectangle([legend_x, PANEL_H + 20, legend_x + 30, PANEL_H + 26], fill=color)
        draw.text((legend_x + 38, PANEL_H + 12), label, fill="black", font=small)
        legend_x += 220
    img.save(sys.argv[2])


if __name__ == "__main__":
    main()
