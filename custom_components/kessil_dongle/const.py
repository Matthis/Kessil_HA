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

# type -> extra channels (besides intensity) exposed as number entities
EXTRA_CHANNELS: Final[dict[int, dict[str, int]]] = {
    2: {"color": CH_COLOR, "red": CH_RED, "amber": CH_AMBER},  # Tuna Sun
}
DEFAULT_EXTRA_CHANNELS: Final[dict[str, int]] = {"color": CH_COLOR}

DEFAULT_BRIGHTNESS: Final = 128

CARD_URL: Final = "/kessil_dongle/kessil-card.js"
