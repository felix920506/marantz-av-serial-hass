"""Declarative descriptions of the receiver settings exposed as entities.

Entities are only created for settings the receiver actually answers, so
these tables can cover every model in the protocol document.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from .protocol import decode_half_step, encode_half_step

# Zone key used for device grouping.
MAIN = "main"
ZONE2 = "zone2"
ZONE3 = "zone3"


@dataclass(frozen=True, kw_only=True)
class SettingDef:
    """Common bits of a setting backed by a state key."""

    key: str
    name: str
    query: str
    zone: str = MAIN
    icon: str | None = None
    config: bool = True
    enabled_default: bool = True


@dataclass(frozen=True, kw_only=True)
class SelectDef(SettingDef):
    """A setting with a fixed set of values."""

    command: str  # format string with {} for the raw value
    options: dict[str, str]  # raw value -> label


@dataclass(frozen=True, kw_only=True)
class SwitchDef(SettingDef):
    """An on/off setting."""

    on_command: str
    off_command: str
    on_value: str = "ON"


def _offset_decode(offset: int) -> Callable[[str], float | None]:
    def _decode(raw: str) -> float | None:
        return int(raw) - offset if raw.strip().isdigit() else None

    return _decode


def _offset_encode(offset: int, width: int = 2) -> Callable[[float], str]:
    def _encode(value: float) -> str:
        return f"{round(value) + offset:0{width}d}"

    return _encode


def _plain_decode(raw: str) -> float | None:
    return int(raw) if raw.strip().isdigit() else None


def _plain_encode(width: int) -> Callable[[float], str]:
    return lambda value: f"{round(value):0{width}d}"


def _level_decode(raw: str) -> float | None:
    value = decode_half_step(raw)
    if value is None or value == 0:  # 00 = speaker off
        return None
    return value - 50


def _level_encode(value: float) -> str:
    return encode_half_step(value + 50)


def _lfe_decode(raw: str) -> float | None:
    return -int(raw) if raw.strip().isdigit() else None


def _lfe_encode(value: float) -> str:
    return f"{abs(round(value)):02d}"


def _sleep_decode(raw: str) -> float | None:
    if raw.strip() == "OFF":
        return 0
    return int(raw) if raw.strip().isdigit() else None


@dataclass(frozen=True, kw_only=True)
class NumberDef(SettingDef):
    """A numeric setting."""

    command: str  # format string with {} for the encoded value
    min_value: float
    max_value: float
    step: float = 1
    unit: str | None = None
    decode: Callable[[str], float | None] = field(default=_plain_decode)
    encode: Callable[[float], str] = field(default=_plain_encode(2))
    zero_command: str | None = None  # command used when value == 0


@dataclass(frozen=True, kw_only=True)
class SensorDef(SettingDef):
    """A read-only value."""

    transform: Callable[[str], str | None] | None = None
    config: bool = False


def _on_off(key: str, name: str, cmd: str, **kwargs) -> SwitchDef:
    """Switch whose commands are ``<cmd>ON``/``<cmd>OFF`` with a query ``<cmd>?``."""
    return SwitchDef(
        key=key,
        name=name,
        query=kwargs.pop("query", f"{cmd}?"),
        on_command=f"{cmd}ON",
        off_command=f"{cmd}OFF",
        **kwargs,
    )


HEAVY_MED_LIGHT = {"HEV": "Heavy", "MED": "Medium", "LIT": "Light", "OFF": "Off"}
STBY_ZONE = {"2H": "2 hours", "4H": "4 hours", "8H": "8 hours", "OFF": "Off"}

SELECTS: tuple[SelectDef, ...] = (
    SelectDef(
        key="DIM",
        name="Display dimmer",
        query="DIM ?",
        command="DIM {}",
        options={"BRI": "Bright", "DIM": "Dim", "DAR": "Dark", "OFF": "Off"},
        icon="mdi:brightness-6",
    ),
    SelectDef(
        key="ILB",
        name="Illumination",
        query="ILB ?",
        command="ILB {}",
        options={
            "AUTO": "Auto",
            "BRI": "Bright",
            "DIM": "Dim",
            "DAR": "Dark",
            "OFF": "Off",
        },
        icon="mdi:lightbulb-on-outline",
    ),
    SelectDef(
        key="ECO",
        name="ECO mode",
        query="ECO?",
        command="ECO{}",
        options={"ON": "On", "AUTO": "Auto", "OFF": "Off"},
        icon="mdi:leaf",
    ),
    SelectDef(
        key="STBY",
        name="Auto standby",
        query="STBY?",
        command="STBY{}",
        options={
            "15M": "15 minutes",
            "30M": "30 minutes",
            "60M": "60 minutes",
            "OFF": "Off",
        },
        icon="mdi:timer-outline",
    ),
    SelectDef(
        key="SD",
        name="Audio input mode",
        query="SD?",
        command="SD{}",
        options={
            "AUTO": "Auto",
            "HDMI": "HDMI",
            "DIGITAL": "Digital",
            "ANALOG": "Analog",
        },
        icon="mdi:import",
    ),
    SelectDef(
        key="MSSMART",
        name="Smart select",
        query="MSSMART ?",
        command="MSSMART{}",
        options={"0": "None", **{str(i): f"Smart {i}" for i in range(1, 6)}},
        icon="mdi:star-outline",
        config=False,
    ),
    SelectDef(
        key="PSMULTEQ",
        name="MultEQ",
        query="PSMULTEQ: ?",
        command="PSMULTEQ:{}",
        options={
            "AUDYSSEY": "Reference",
            "BYP.LR": "L/R Bypass",
            "FLAT": "Flat",
            "OFF": "Off",
        },
        icon="mdi:tune-vertical",
    ),
    SelectDef(
        key="PSREFLEV",
        name="Dynamic EQ reference level offset",
        query="PSREFLEV ?",
        command="PSREFLEV {}",
        options={"0": "0 dB", "5": "5 dB", "10": "10 dB", "15": "15 dB"},
        icon="mdi:tune-vertical",
    ),
    SelectDef(
        key="PSDYNVOL",
        name="Dynamic volume",
        query="PSDYNVOL ?",
        command="PSDYNVOL {}",
        options=HEAVY_MED_LIGHT,
        icon="mdi:volume-equal",
    ),
    SelectDef(
        key="PSSURLEV",
        name="Surround level compensation",
        query="PSSURLEV ?",
        command="PSSURLEV {}",
        options=HEAVY_MED_LIGHT,
        icon="mdi:surround-sound",
    ),
    SelectDef(
        key="PSDRC",
        name="Dynamic range compression",
        query="PSDRC ?",
        command="PSDRC {}",
        options={
            "AUTO": "Auto",
            "LOW": "Low",
            "MID": "Medium",
            "HI": "High",
            "OFF": "Off",
        },
        icon="mdi:arrow-collapse-vertical",
    ),
    SelectDef(
        key="PSDEH",
        name="Dialog enhancer",
        query="PSDEH ?",
        command="PSDEH {}",
        options={"OFF": "Off", "LOW": "Low", "MED": "Medium", "HIGH": "High"},
        icon="mdi:account-voice",
    ),
    SelectDef(
        key="PSMDAX",
        name="M-DAX",
        query="PSMDAX ?",
        command="PSMDAX {}",
        options={"OFF": "Off", "LOW": "Low", "MED": "Medium", "HI": "High"},
        icon="mdi:music-note-plus",
    ),
    SelectDef(
        key="PSDIRAC",
        name="Dirac Live filter",
        query="PSDIRAC ?",
        command="PSDIRAC {}",
        options={"1": "Slot 1", "2": "Slot 2", "3": "Slot 3", "OFF": "Off"},
        icon="mdi:tune",
    ),
    SelectDef(
        key="PSIMAX",
        name="IMAX mode",
        query="PSIMAX ?",
        command="PSIMAX {}",
        options={"AUTO": "Auto", "OFF": "Off"},
        icon="mdi:filmstrip",
    ),
    SelectDef(
        key="PSIMAXAUD",
        name="IMAX audio settings",
        query="PSIMAXAUD ?",
        command="PSIMAXAUD {}",
        options={"AUTO": "Auto", "MANUAL": "Manual"},
        icon="mdi:filmstrip",
    ),
    SelectDef(
        key="PSIMAXHPF",
        name="IMAX high pass filter",
        query="PSIMAXHPF ?",
        command="PSIMAXHPF {}",
        options={
            f"{hz:03d}": f"{hz} Hz"
            for hz in (40, 60, 70, 80, 90, 100, 110, 120, 150, 180, 200, 250)
        },
        icon="mdi:filmstrip",
    ),
    SelectDef(
        key="PSIMAXLPF",
        name="IMAX low pass filter",
        query="PSIMAXLPF ?",
        command="PSIMAXLPF {}",
        options={
            f"{hz:03d}": f"{hz} Hz"
            for hz in (70, 80, 90, 100, 110, 120, 150, 180, 200, 250)
        },
        icon="mdi:filmstrip",
    ),
    SelectDef(
        key="PSIMAXSWO",
        name="IMAX subwoofer output",
        query="PSIMAXSWO ?",
        command="PSIMAXSWO {}",
        options={"L+M": "LFE + Main", "LFE": "LFE"},
        icon="mdi:filmstrip",
    ),
    SelectDef(
        key="PSAUROPR",
        name="Auro-Matic 3D preset",
        query="PSAUROPR ?",
        command="PSAUROPR {}",
        options={
            "SMA": "Small",
            "MED": "Medium",
            "LAR": "Large",
            "SPE": "Speech",
            "MOV": "Movie",
        },
        icon="mdi:surround-sound",
    ),
    SelectDef(
        key="PSAUROMODE",
        name="Auro-3D mode",
        query="PSAUROMODE ?",
        command="PSAUROMODE {}",
        options={"DRCT": "Direct", "EXP": "Channel expansion"},
        icon="mdi:surround-sound",
    ),
    SelectDef(
        key="PSDACFIL",
        name="DAC filter",
        query="PSDACFIL ?",
        command="PSDACFIL {}",
        options={"MODE1": "Mode 1", "MODE2": "Mode 2"},
        icon="mdi:sine-wave",
    ),
    SelectDef(
        key="PSFRONT",
        name="Front speakers",
        query="PSFRONT?",
        command="PSFRONT {}",
        options={"SPA": "A", "SPB": "B", "A+B": "A+B"},
        icon="mdi:speaker-multiple",
    ),
    SelectDef(
        key="PSSP",
        name="Effect speakers",
        query="PSSP: ?",
        command="PSSP:{}",
        options={"FL": "Floor", "HF": "Height & floor"},
        icon="mdi:speaker-multiple",
    ),
    SelectDef(
        key="SPPR",
        name="Speaker preset",
        query="SPPR ?",
        command="SPPR {}",
        options={"1": "Preset 1", "2": "Preset 2"},
        icon="mdi:speaker-multiple",
    ),
    SelectDef(
        key="VSMONI",
        name="HDMI monitor output",
        query="VSMONI ?",
        command="VSMONI{}",
        options={"AUTO": "Auto", "1": "Monitor 1", "2": "Monitor 2"},
        icon="mdi:television",
    ),
    SelectDef(
        key="VSAUDIO",
        name="HDMI audio output",
        query="VSAUDIO ?",
        command="VSAUDIO {}",
        options={"AMP": "AMP", "TV": "TV"},
        icon="mdi:television-speaker",
    ),
    SelectDef(
        key="VSVPM",
        name="Video processing mode",
        query="VSVPM ?",
        command="VSVPM{}",
        options={"AUTO": "Auto", "GAME": "Game", "MOVI": "Movie", "BYP": "Bypass"},
        icon="mdi:television",
    ),
    SelectDef(
        key="BTTX",
        name="Bluetooth output mode",
        query="BTTX ?",
        command="BTTX {}",
        options={"SP": "Bluetooth + speakers", "BT": "Bluetooth only"},
        icon="mdi:bluetooth-audio",
    ),
    SelectDef(
        key="TMAN",
        name="Tuner band",
        query="TMAN?",
        command="TMAN{}",
        options={"AM": "AM", "FM": "FM", "DAB": "DAB"},
        icon="mdi:radio",
        config=False,
    ),
    # Zone 2
    SelectDef(
        key="Z2STBY",
        name="Auto standby",
        query="Z2STBY?",
        command="Z2STBY{}",
        options=STBY_ZONE,
        zone=ZONE2,
        icon="mdi:timer-outline",
    ),
    SelectDef(
        key="Z2CS",
        name="Channel mode",
        query="Z2CS?",
        command="Z2CS{}",
        options={"ST": "Stereo", "MONO": "Mono"},
        zone=ZONE2,
        icon="mdi:speaker",
    ),
    SelectDef(
        key="Z2HDA",
        name="HDMI audio",
        query="Z2HDA?",
        command="Z2HDA {}",
        options={"THR": "Through", "PCM": "PCM"},
        zone=ZONE2,
        icon="mdi:television-speaker",
    ),
    SelectDef(
        key="Z2SMART",
        name="Smart select",
        query="Z2SMART ?",
        command="Z2SMART{}",
        options={"0": "None", **{str(i): f"Smart {i}" for i in range(1, 6)}},
        zone=ZONE2,
        icon="mdi:star-outline",
        config=False,
    ),
    # Zone 3
    SelectDef(
        key="Z3STBY",
        name="Auto standby",
        query="Z3STBY?",
        command="Z3STBY{}",
        options=STBY_ZONE,
        zone=ZONE3,
        icon="mdi:timer-outline",
    ),
    SelectDef(
        key="Z3CS",
        name="Channel mode",
        query="Z3CS?",
        command="Z3CS{}",
        options={"ST": "Stereo", "MONO": "Mono"},
        zone=ZONE3,
        icon="mdi:speaker",
    ),
    SelectDef(
        key="Z3SMART",
        name="Smart select",
        query="Z3SMART ?",
        command="Z3SMART{}",
        options={"0": "None", **{str(i): f"Smart {i}" for i in range(1, 6)}},
        zone=ZONE3,
        icon="mdi:star-outline",
        config=False,
    ),
)


SWITCHES: tuple[SwitchDef, ...] = (
    _on_off(
        "PSTONE CTRL",
        "Tone control",
        "PSTONE CTRL ",
        query="PSTONE CTRL ?",
        icon="mdi:tune-variant",
    ),
    _on_off(
        "PSDYNEQ", "Dynamic EQ", "PSDYNEQ ", query="PSDYNEQ ?", icon="mdi:tune-vertical"
    ),
    _on_off(
        "PSCINEMA EQ",
        "Cinema EQ",
        "PSCINEMA EQ.",
        query="PSCINEMA EQ. ?",
        icon="mdi:filmstrip",
    ),
    _on_off(
        "PSLOM",
        "Loudness management",
        "PSLOM ",
        query="PSLOM ?",
        icon="mdi:volume-high",
    ),
    _on_off("PSGEQ", "Graphic EQ", "PSGEQ ", query="PSGEQ ?", icon="mdi:equalizer"),
    _on_off("PSHEQ", "Headphone EQ", "PSHEQ ", query="PSHEQ ?", icon="mdi:headphones"),
    _on_off(
        "PSCES", "Center spread", "PSCES ", query="PSCES ?", icon="mdi:surround-sound"
    ),
    _on_off(
        "PSSPV",
        "Speaker virtualizer",
        "PSSPV ",
        query="PSSPV ?",
        icon="mdi:surround-sound",
    ),
    _on_off(
        "PSNEURAL",
        "Neural:X",
        "PSNEURAL ",
        query="PSNEURAL ?",
        icon="mdi:surround-sound",
    ),
    _on_off(
        "PSLFC", "Audyssey LFC", "PSLFC ", query="PSLFC ?", icon="mdi:home-sound-out"
    ),
    _on_off(
        "PSSWR",
        "Subwoofer in Direct/Stereo",
        "PSSWR ",
        query="PSSWR ?",
        icon="mdi:speaker",
    ),
    _on_off(
        "BTTX:ONOFF",
        "Bluetooth transmitter",
        "BTTX ",
        query="BTTX ?",
        icon="mdi:bluetooth-audio",
    ),
    _on_off(
        "CVTTR:ONOFF",
        "Tactile transducer",
        "CVTTR ",
        query="CVTTR ?",
        icon="mdi:vibrate",
    ),
    _on_off(
        "MNZST",
        "All zone stereo",
        "MNZST ",
        query="MNZST?",
        icon="mdi:speaker-multiple",
        config=False,
    ),
    SwitchDef(
        key="VSSCH",
        name="HDMI upscaler",
        query="VSSCH ?",
        on_command="VSSCHAUTO",
        off_command="VSSCHOFF",
        on_value="AUTO",
        icon="mdi:arrow-expand-all",
    ),
    _on_off("TR1", "Trigger 1", "TR1 ", query="TR?", icon="mdi:electric-switch"),
    _on_off("TR2", "Trigger 2", "TR2 ", query="TR?", icon="mdi:electric-switch"),
    _on_off("TR3", "Trigger 3", "TR3 ", query="TR?", icon="mdi:electric-switch"),
    _on_off(
        "Z2HPF", "High pass filter", "Z2HPF", zone=ZONE2, icon="mdi:filter-outline"
    ),
    _on_off(
        "Z3HPF", "High pass filter", "Z3HPF", zone=ZONE3, icon="mdi:filter-outline"
    ),
)


def _tone(key: str, name: str, cmd: str, limit: int, zone: str = MAIN) -> NumberDef:
    return NumberDef(
        key=key,
        name=name,
        query=f"{cmd} ?",
        command=f"{cmd} {{}}",
        min_value=-limit,
        max_value=limit,
        unit="dB",
        decode=_offset_decode(50),
        encode=_offset_encode(50),
        zone=zone,
        icon="mdi:tune-vertical-variant",
    )


def _level(
    key: str, name: str, cmd: str, query: str, zone: str = MAIN, **kwargs
) -> NumberDef:
    return NumberDef(
        key=key,
        name=name,
        query=query,
        command=f"{cmd} {{}}",
        min_value=-12,
        max_value=12,
        step=0.5,
        unit="dB",
        decode=_level_decode,
        encode=_level_encode,
        zone=zone,
        icon=kwargs.pop("icon", "mdi:volume-equal"),
        **kwargs,
    )


# Channel code -> name, as reported by CV?
CHANNELS: dict[str, str] = {
    "FL": "Front left",
    "FR": "Front right",
    "C": "Center",
    "SW": "Subwoofer",
    "SW2": "Subwoofer 2",
    "SW3": "Subwoofer 3",
    "SW4": "Subwoofer 4",
    "SL": "Surround left",
    "SR": "Surround right",
    "SBL": "Surround back left",
    "SBR": "Surround back right",
    "SB": "Surround back",
    "FHL": "Front height left",
    "FHR": "Front height right",
    "FWL": "Front wide left",
    "FWR": "Front wide right",
    "TFL": "Top front left",
    "TFR": "Top front right",
    "TML": "Top middle left",
    "TMR": "Top middle right",
    "TRL": "Top rear left",
    "TRR": "Top rear right",
    "RHL": "Rear height left",
    "RHR": "Rear height right",
    "FDL": "Front Dolby left",
    "FDR": "Front Dolby right",
    "SDL": "Surround Dolby left",
    "SDR": "Surround Dolby right",
    "BDL": "Back Dolby left",
    "BDR": "Back Dolby right",
    "SHL": "Surround height left",
    "SHR": "Surround height right",
    "TS": "Top surround",
    "CH": "Center height",
}


NUMBERS: tuple[NumberDef, ...] = (
    _tone("PSBAS", "Bass", "PSBAS", 6),
    _tone("PSTRE", "Treble", "PSTRE", 6),
    NumberDef(
        key="PSLFE",
        name="LFE level",
        query="PSLFE ?",
        command="PSLFE {}",
        min_value=-10,
        max_value=0,
        unit="dB",
        decode=_lfe_decode,
        encode=_lfe_encode,
        icon="mdi:speaker",
    ),
    NumberDef(
        key="PSDIC",
        name="Dialog control",
        query="PSDIC ?",
        command="PSDIC {}",
        min_value=0,
        max_value=6,
        icon="mdi:account-voice",
    ),
    NumberDef(
        key="PSBSC",
        name="Bass sync",
        query="PSBSC ?",
        command="PSBSC {}",
        min_value=0,
        max_value=16,
        icon="mdi:sine-wave",
    ),
    NumberDef(
        key="PSCNTAMT",
        name="Containment amount",
        query="PSCNTAMT ?",
        command="PSCNTAMT {}",
        min_value=1,
        max_value=7,
        icon="mdi:home-sound-out",
    ),
    NumberDef(
        key="PSAUROST",
        name="Auro-Matic 3D strength",
        query="PSAUROST ?",
        command="PSAUROST {}",
        min_value=1,
        max_value=16,
        icon="mdi:surround-sound",
    ),
    NumberDef(
        key="PSDELAY",
        name="Audio delay",
        query="PSDELAY ?",
        command="PSDELAY {}",
        min_value=0,
        max_value=500,
        unit="ms",
        encode=_plain_encode(3),
        icon="mdi:timer-sand",
    ),
    _level("PSSWL", "Subwoofer level", "PSSWL", "PSSWL ?", icon="mdi:speaker"),
    _level("PSSWL2", "Subwoofer 2 level", "PSSWL2", "PSSWL ?", icon="mdi:speaker"),
    _level("PSSWL3", "Subwoofer 3 level", "PSSWL3", "PSSWL ?", icon="mdi:speaker"),
    _level("PSSWL4", "Subwoofer 4 level", "PSSWL4", "PSSWL ?", icon="mdi:speaker"),
    _level("CVTTR", "Tactile transducer level", "CVTTR", "CVTTR ?", icon="mdi:vibrate"),
    *(
        _level(f"CV{code}", f"{name} level", f"CV{code}", "CV?", enabled_default=True)
        for code, name in CHANNELS.items()
    ),
    NumberDef(
        key="SLP",
        name="Sleep timer",
        query="SLP?",
        command="SLP{}",
        zero_command="SLPOFF",
        min_value=0,
        max_value=120,
        unit="min",
        decode=_sleep_decode,
        encode=_plain_encode(3),
        icon="mdi:sleep",
        config=False,
    ),
    NumberDef(
        key="TPAN",
        name="Tuner preset",
        query="TPAN?",
        command="TPAN{}",
        min_value=1,
        max_value=56,
        icon="mdi:radio",
        config=False,
    ),
    # Zone 2
    _tone("Z2PSBAS", "Bass", "Z2PSBAS", 10, ZONE2),
    _tone("Z2PSTRE", "Treble", "Z2PSTRE", 10, ZONE2),
    _level("Z2CVFL", "Front left level", "Z2CVFL", "Z2CV?", ZONE2),
    _level("Z2CVFR", "Front right level", "Z2CVFR", "Z2CV?", ZONE2),
    NumberDef(
        key="Z2SLP",
        name="Sleep timer",
        query="Z2SLP?",
        command="Z2SLP{}",
        zero_command="Z2SLPOFF",
        min_value=0,
        max_value=120,
        unit="min",
        decode=_sleep_decode,
        encode=_plain_encode(3),
        zone=ZONE2,
        icon="mdi:sleep",
        config=False,
    ),
    # Zone 3
    _tone("Z3PSBAS", "Bass", "Z3PSBAS", 10, ZONE3),
    _tone("Z3PSTRE", "Treble", "Z3PSTRE", 10, ZONE3),
    _level("Z3CVFL", "Front left level", "Z3CVFL", "Z3CV?", ZONE3),
    _level("Z3CVFR", "Front right level", "Z3CVFR", "Z3CV?", ZONE3),
    NumberDef(
        key="Z3SLP",
        name="Sleep timer",
        query="Z3SLP?",
        command="Z3SLP{}",
        zero_command="Z3SLPOFF",
        min_value=0,
        max_value=120,
        unit="min",
        decode=_sleep_decode,
        encode=_plain_encode(3),
        zone=ZONE3,
        icon="mdi:sleep",
        config=False,
    ),
)


def _sample_rate(raw: str) -> str | None:
    raw = raw.strip()
    if not raw.isdigit():
        return None
    # Reported in units of 100 Hz, e.g. 441 -> 44.1 kHz, 480 -> 48 kHz.
    khz = int(raw) / 10
    return f"{khz:g} kHz"


def _tuner_frequency(raw: str) -> str | None:
    raw = raw.strip()
    if not raw.isdigit() or len(raw) != 6:
        return None
    value = int(raw) / 100
    if int(raw) >= 50000:
        return f"{value:g} kHz"
    return f"{value:.2f} MHz"


def _resolution(raw: str) -> str | None:
    raw = raw.strip()
    if not raw or set(raw) == {"-"}:
        return "No signal"
    return raw


SENSORS: tuple[SensorDef, ...] = (
    SensorDef(
        key="SYSMI", name="Surround mode", query="MS?", icon="mdi:surround-sound"
    ),
    SensorDef(key="SYSDA", name="Audio input signal", query="MS?", icon="mdi:waveform"),
    SensorDef(
        key="SSINFAISFSV",
        name="Audio sample rate",
        query="SSINFAISFSV ?",
        transform=_sample_rate,
        icon="mdi:sine-wave",
    ),
    SensorDef(
        key="SSINFSIGRESI",
        name="Video input resolution",
        query="SSINFSIGRES ?",
        transform=_resolution,
        icon="mdi:video-input-hdmi",
    ),
    SensorDef(
        key="SSINFSIGRESO",
        name="Video output resolution",
        query="SSINFSIGRES ?",
        transform=_resolution,
        icon="mdi:television",
    ),
    SensorDef(
        key="TFAN",
        name="Tuner frequency",
        query="TFAN?",
        transform=_tuner_frequency,
        icon="mdi:radio",
    ),
)


def all_queries() -> list[str]:
    """Return the unique queries needed to refresh every setting."""
    seen: dict[str, None] = {}
    for defs in (SELECTS, SWITCHES, NUMBERS, SENSORS):
        for item in defs:
            seen.setdefault(item.query, None)
    return list(seen)
