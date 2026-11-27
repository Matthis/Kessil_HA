# Home Assistant (HA) Integration for Kessil Wifi Dongle

Unofficial, local-only Home Assistant integration for the **Kessil WiFi dongle**
(KSAWD01), developed with **A360X Tuna Sun** lamps. Includes a Lovelace card with an
intensity dial, spectrum sliders, mode buttons and the daily curve.

> Not affiliated with or endorsed by Kessil. "Kessil" is used only to describe
> which device this works with.

## Features

Per lamp group on the dongle:

| Entity | What it does |
|---|---|
| `light` | On/off and intensity. Any change switches the group to manual mode. |
| `number` Intensity / Color / Red / Amber | Channels in % (Tuna Sun) |
| `select` Mode | `Manual` or one of the programs stored on the dongle |
| `sensor` Lamps | Number of lamps in the group (diagnostic) |

Plus one overheat status sensor per lamp (diagnostic).

Each lamp group becomes one device, named after the lamp type
(e.g. *Kessil Tuna Sun Group*). The dongle itself and single lamps are not separate devices.

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

The card is shipped with the integration and loaded automatically – no extra
resource needed.

```yaml
type: custom:kessil-card
entity: light.kessil_tuna_sun_group
name: Aquarium   # optional
```

The other entities (color, red, amber, mode) are found automatically through the
light's device.

- Drag the ring to set the intensity, tap the centre to toggle on/off.
- Changing intensity or a slider switches to manual mode; tap a program to return.
- The daily curve shows intensity (solid) and color (dashed) of the running
  program – or of the first program while in manual mode – with a marker for now.

## Notes

- The dongle's daily program runs on the dongle's own clock and time zone.
- While a program runs, the dongle does not report the lamps' current output, only
  the stored manual values. The integration therefore computes the current values
  from the program curve (linear fade between points, dongle time zone).
- Only Tuna Sun channel mapping is verified. Other lamp types get intensity and
  color only.
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
