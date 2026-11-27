"""Constants for the Kessil WiFi dongle integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "kessil_dongle"
MANUFACTURER: Final = "Kessil"

SCAN_INTERVAL: Final = timedelta(seconds=60)
# Lamps, system info and programs change rarely: refresh every N polls.
SLOW_REFRESH_EVERY: Final = 10

# Index into the 5-value UI array, per group type. Only Tuna Sun is verified.
CH_INTENSITY: Final = 0
CH_COLOR: Final = 1
CH_RED: Final = 3
CH_AMBER: Final = 4

# type -> channels exposed as number entities (intensity is also the light):
# key -> (index, maximum raw value). Intensity and color go to 255; on Tuna Sun
# the dongle rejects red/amber above 100 ("Invalid command format").
EXTRA_CHANNELS: Final[dict[int, dict[str, tuple[int, int]]]] = {
    2: {  # Tuna Sun
        "intensity": (CH_INTENSITY, 255),
        "color": (CH_COLOR, 255),
        "red": (CH_RED, 100),
        "amber": (CH_AMBER, 100),
    },
}
DEFAULT_EXTRA_CHANNELS: Final[dict[str, tuple[int, int]]] = {
    "intensity": (CH_INTENSITY, 255),
    "color": (CH_COLOR, 255),
}

# Channels that emit light on their own. On Tuna Sun, red and amber are separate
# LEDs that stay lit at intensity 0, so "off" must zero all of them.
LIGHT_CHANNELS: Final[dict[int, tuple[int, ...]]] = {2: (CH_INTENSITY, CH_RED, CH_AMBER)}
DEFAULT_LIGHT_CHANNELS: Final[tuple[int, ...]] = (CH_INTENSITY,)


def light_channels(group_type: int) -> tuple[int, ...]:
    return LIGHT_CHANNELS.get(group_type, DEFAULT_LIGHT_CHANNELS)


DEFAULT_BRIGHTNESS: Final = 128

CARD_URL: Final = "/kessil_dongle/kessil-card.js"
