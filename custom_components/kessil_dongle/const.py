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

# type -> extra channels (besides intensity) exposed as number entities:
# key -> (index, maximum raw value). Intensity and color go to 255; on Tuna Sun
# the dongle rejects red/amber above 100 ("Invalid command format").
EXTRA_CHANNELS: Final[dict[int, dict[str, tuple[int, int]]]] = {
    2: {"color": (CH_COLOR, 255), "red": (CH_RED, 100), "amber": (CH_AMBER, 100)},  # Tuna Sun
}
DEFAULT_EXTRA_CHANNELS: Final[dict[str, tuple[int, int]]] = {"color": (CH_COLOR, 255)}

DEFAULT_BRIGHTNESS: Final = 128

CARD_URL: Final = "/kessil_dongle/kessil-card.js"
