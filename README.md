# Marantz AVR (RS-232C / IP) for Home Assistant

A Home Assistant custom integration that controls Marantz AV receivers
through their **RS-232C / telnet control protocol**. It reaches the settings
that the HEOS integration can't: surround modes, Audyssey/Dirac, tone,
channel levels, zones, triggers, the display dimmer, and more.

Built from the *Marantz FY23 (CY2022) AV CINEMA protocol, v06* (CINEMA 40 / 50 /
60 / 70s, AV 10). It should also work with other Marantz and Denon receivers
that use the same command set. Tested on a **CINEMA 40** over both telnet and
an RS-232 serial server.

## Connection options

| Type | Example | Notes |
| --- | --- | --- |
| Network (telnet) | host `192.168.1.50`, port `23` | Set *Network > Network Control* to **Always On** so the receiver can be turned on from standby. |
| Raw TCP serial server | `socket://192.168.1.60:4001` | e.g. USR/Moxa/ser2net in raw TCP mode, 9600 8N1 |
| RFC2217 serial server | `rfc2217://192.168.1.60:4001` | |
| Local serial port | `/dev/ttyUSB0`, `/dev/serial/by-id/...` | 9600 baud, 8N1, straight-through cable |

Communication is push-based. The receiver reports every change as it
happens, so Home Assistant stays in sync with the front panel, the IR remote,
and the HEOS app.

## Installation (HACS)

1. In HACS, open the menu, choose **Custom repositories**, and add
   `https://github.com/felix920506/marantz-av-serial-hass` with type **Integration**.
2. Install **Marantz AVR (RS-232C / IP)** and restart Home Assistant.
3. Go to **Settings → Devices & services → Add integration → Marantz AVR**.

Manual install: copy `custom_components/marantz_avr` into your
`config/custom_components` folder and restart.

## Entities

The integration asks the receiver for every setting the protocol defines and
creates entities **only for the settings your model answers**. The list of
supported settings is cached, so entities stay in place even if the receiver
is unreachable when Home Assistant starts.

- **Media players:** the main zone, plus Zone 2 and Zone 3 when present. Each
  supports power, volume (0.5 dB steps; `volume_level` maps to the front-panel
  0–98 scale, and `volume_db` is an attribute), mute, and source. The main
  zone also has surround mode. Zones can follow the main zone's source.
- **Selects:** dimmer, illumination, ECO, auto standby, audio input mode, smart
  select, MultEQ, Dynamic EQ reference offset, Dynamic Volume, surround level
  compensation, DRC, dialog enhancer, M-DAX, Dirac Live slot, IMAX settings,
  Auro-3D settings, front speaker A/B, effect speakers, speaker preset, HDMI
  monitor / audio output, video processing mode, Bluetooth output mode, tuner
  band, and per-zone settings.
- **Switches:** tone control, Dynamic EQ, Cinema EQ, loudness management,
  graphic EQ, headphone EQ, center spread, speaker virtualizer, Neural:X,
  Audyssey LFC, subwoofer in Direct/Stereo, Bluetooth transmitter, tactile
  transducer, all-zone stereo, HDMI upscaler, triggers 1–3, and the zone high
  pass filters.
- **Numbers:** bass/treble (per zone), every speaker channel level the
  receiver reports, subwoofer level(s), LFE, dialog control, bass sync,
  containment amount, Auro-Matic strength, audio delay, sleep timers, and
  tuner preset.
- **Sensors:** surround mode (as displayed), input audio format, sample rate,
  video input/output resolution, and tuner frequency. Sample rate and
  resolution are available over IP only.
- **Remote:** turning it on or off controls *system* power (all zones).
  `remote.send_command` accepts named keys (`up`, `down`, `left`, `right`,
  `enter`, `back`, `menu_on`, `menu_off`, `option`, `info`, `channel_level`,
  `next_sound_mode`, `previous_sound_mode`, `dimmer`, `tuner_preset_up`, …) or
  **any raw protocol command**:

```yaml
action: remote.send_command
target:
  entity_id: remote.marantz_cinema_40
data:
  command:
    - PSDYNEQ ON
    - MSMOVIE
```

### Options

**Configure** lets you pick which input sources appear in the source list.
Over IP, the receiver's own source names (renamed inputs) and hidden-source
settings are read automatically. Over RS-232 the receiver doesn't expose
them, so the defaults from the protocol document are used.

## Development

```sh
python3.13 -m venv .venv && . .venv/bin/activate
pip install -r requirements_test.txt
pytest                     # unit + integration tests against a fake receiver
ruff check .

# Optional: live tests against a real receiver (changes and restores a few
# harmless settings: volume, mute, dimmer, sound mode, source, bass)
MARANTZ_LIVE_HOST=192.168.1.50 \
MARANTZ_LIVE_SERIAL_URL=socket://192.168.1.60:4001 \
pytest tests/test_live.py -s
```

The protocol client (`custom_components/marantz_avr/protocol.py`) has no Home
Assistant dependencies.
