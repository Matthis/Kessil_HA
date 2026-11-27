<img src="custom_components/kessil_dongle/brand/icon.png" alt="" width="96" align="right">

# Home Assistant (HA) Integration for Kessil Wifi Dongle

Unofficial, local-only Home Assistant integration for the **Kessil WiFi dongle**
(KSAWD01), developed with **A360X Tuna Sun** lamps. The KSAWD01 works with the
A360X, A360XE and A500X (via K-Link); only Tuna Sun has been tested. Includes a Lovelace card with mode
buttons, the daily curve and channel sliders.

> Not affiliated with or endorsed by Kessil. "Kessil" is used only to describe
> which device this works with.

## Features

Per lamp group on the dongle:

| Entity | What it does |
|---|---|
| `light` | Operating state and intensity (see below). |
| `number` Intensity / Color temperature / Red / Amber | Channels in % (Tuna Sun; other lamp types: Intensity / Spectrum) |
| `select` Mode | `Manual` or one of the programs stored on the dongle |
| `sensor` Lamps | Number of lamps in the group (diagnostic) |

Plus one overheat status sensor per lamp (diagnostic).

**On/off** shows the operating state rather than a power switch:

| State | Light |
|---|---|
| A program runs (even while its values are 0, e.g. at night) | on |
| Manual, intensity, red and amber all 0 | off |
| Manual, at least one of them above 0 | on |

Red and amber are separate LEDs, so they count on their own. Turning *off*
switches to manual with these channels at 0. Turning *on* switches to manual with
the intensity stored in the dongle (about 50 % if that is 0). Any slider change
also switches to manual, starting from the manual values stored in the dongle.
Home Assistant does not remember any values itself.

Each lamp group becomes one device, named after the lamp type as in the Kessil app
(e.g. *Kessil Group - Tuna Sun*). The dongle itself and single lamps are not separate devices.

Communication is local TCP (port 8888), polled every 60 seconds. No cloud, no app
needed after the dongle has been set up once.

## Installation

### HACS (custom repository)

1. HACS → ⋮ → *Custom repositories* → add `https://github.com/Matthis/Kessil_HA`,
   category *Integration*.
2. Install **Kessil WiFi Dongle** and restart Home Assistant.

### Manual

Copy `custom_components/kessil_dongle` into your HA `config/custom_components/`
folder and restart.

### Setup

*Settings → Devices & services → Add integration → Kessil WiFi Dongle*, then enter
the dongle's IP address. Give the dongle a fixed IP (DHCP reservation). If HA and the
dongle are in different VLANs, allow TCP 8888 from HA to the dongle.

## Lovelace card

<img src="docs/images/card.png" alt="Kessil card in Home Assistant" width="420">

The card is shipped with the integration and loaded automatically – no extra
resource needed.

```yaml
type: custom:kessil-card
entity: light.kessil_group_tuna_sun
name: Aquarium   # optional
```

The other entities (intensity, color temperature, red, amber, mode) are found
automatically through the light's device.

- Top right: the daily light amount of the running program, in hours at full
  intensity (in manual mode: intensity × 24 h).
- Top: mode buttons (manual or one of the dongle's programs) and the daily curve
  with intensity (solid), color temperature (dashed), a marker for now and a
  cloud-with-lightning symbol where the program has a thunderstorm effect. In manual
  mode the curve is a constant line at the current values.
- Below: sliders for intensity, color temperature, red and amber. For Tuna Sun groups
  the color temperature slider shows the range (warm 6000 K – 9000 K cool); other
  lamp types get a neutral "Spectrum" slider. Moving one switches
  to manual mode, starting from the manual values stored in the dongle.

## Example program: Natural Day

[`programs/natural_day.json`](programs/natural_day.json) is a suggestion for a
natural daily curve for Tuna Sun: light from 07:30 to 17:00 with a daily light
amount of about 6 hours at full intensity, shaped like a real day.

![Natural Day](docs/images/natural_day.png)

| Time | What happens |
|---|---|
| 07:30–08:10 | Dawn: amber glows first, red joins; sunrise peak at 08:10 in deep orange (amber 100, red 52) with almost no intensity |
| 08:10–10:00 | Morning: amber and red fade, intensity rises smoothly, color temperature moves from warm to neutral |
| 10:00–13:05 | Midday: slow rise to the zenith at 13:05 (intensity 93 %, color temperature 71 %) |
| 13:10 | Thunderstorm: the dongle's own storm effect for 5 minutes, then it clears up |
| 14:30–16:30 | Afternoon: gradually warmer and dimmer; sunset glow at 16:30 (amber 100, red 56) |
| 16:30–17:00 | Dusk: red and amber fade out, night from 17:00 |

The file uses the dongle's program format (points with `minutes`, `UI`, `eid`,
`duration`, `freq`). It cannot be uploaded from Home Assistant yet. Adapt it with
`scripts/natural_day.py` (the shape table at the top; channel amounts are scaled to
a reference program) and draw it with `scripts/plot_program.py`.

## Roadmap

- **Program management**: back up and restore the dongle's programs, create,
  rename and delete programs from Home Assistant, and edit the daily curve in the
  card (e.g. to upload [Natural Day](#example-program-natural-day)).
- **Generated daily program**: sunrise and sunset following the real sun times
  and a random midday thunderstorm, written to the dongle once a day (so the
  lamps keep running on their own if Home Assistant is down).
- **Acclimation and moon phase** settings, which the dongle already reports.
- **More lamp types**: Tuna Blue, A500X and Refugium are untested. If you own one,
  please open an issue. Anonymised responses of the read-only commands in
  [docs/PROTOCOL.md](docs/PROTOCOL.md) (102, 105, 106) are enough to start.

## Notes

- The dongle's daily program runs on the dongle's own clock and time zone.
- While a program runs, the dongle does not report the lamps' current output, only
  the stored manual values. The integration therefore computes the current values
  from the program curve (linear fade between points, dongle time zone).
- Only Tuna Sun channel mapping is verified. Other lamp types get intensity and
  color only.
- The integration icon (shown from Home Assistant 2026.3) is original artwork,
  generated by `scripts/make_icon.py`; it is not a Kessil logo.
- Protocol details: [docs/PROTOCOL.md](docs/PROTOCOL.md).

## Development

```sh
uv venv --python 3.13 .venv
uv pip install --python .venv -r requirements_test.txt
.venv/bin/python -m pytest
```

Tests run against a fake dongle (recorded, anonymised responses in
`tests/fixtures/`) and a real Home Assistant core – no device needed.

## License

MIT – see [LICENSE](LICENSE).
