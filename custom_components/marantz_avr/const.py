"""Constants for the Marantz AVR integration."""

from __future__ import annotations

DOMAIN = "marantz_avr"
MANUFACTURER = "Marantz"

CONF_CONNECTION_TYPE = "connection_type"
CONF_SERIAL_URL = "serial_url"
CONF_SOURCES = "sources"

CONNECTION_NETWORK = "network"
CONNECTION_SERIAL = "serial"

DEFAULT_NETWORK_PORT = 23

# Input source code -> default display name, in front panel order.
SOURCES: dict[str, str] = {
    "PHONO": "Phono",
    "CD": "CD",
    "BD": "Blu-ray",
    "TV": "TV Audio",
    "SAT/CBL": "CBL/SAT",
    "MPLAY": "Media Player",
    "GAME1": "Game1",
    "GAME2": "Game2",
    "TUNER": "Tuner",
    "AUX1": "AUX1",
    "AUX2": "AUX2",
    "AUX3": "AUX3",
    "AUX4": "AUX4",
    "AUX5": "AUX5",
    "AUX6": "AUX6",
    "AUX7": "AUX7",
    "NET": "HEOS Music",
    "BT": "Bluetooth",
}
# Sources that only exist when "Additional Source" is enabled (AV 10).
OPTIONAL_SOURCES = frozenset({"AUX3", "AUX4", "AUX5", "AUX6", "AUX7"})
# Legacy source codes the receiver may report.
SOURCE_ALIASES = {"GAME": "GAME1", "CBL/SAT": "SAT/CBL"}

ZONE_FOLLOW_MAIN = "SOURCE"

# Surround modes that can be selected directly (MS<mode>).
SOUND_MODES: list[str] = [
    "AUTO",
    "MOVIE",
    "MUSIC",
    "GAME",
    "DIRECT",
    "PURE DIRECT",
    "STEREO",
    "MCH STEREO",
    "DOLBY DIGITAL",
    "DTS SURROUND",
    "NEURAL:X",
    "AURO3D",
    "AURO2DSURR",
]

# Queries that make up a full status refresh (in addition to the per-entity
# queries in entity_defs).
BASE_QUERIES: tuple[str, ...] = (
    "PW?",
    "ZM?",
    "MV?",
    "MU?",
    "SI?",
    "MS?",
    "SD?",
    "SV?",
    "CV?",
    "Z2?",
    "Z2MU?",
    "Z3?",
    "Z3MU?",
    "SYMO",
    "NSFRN ?",
    "SSFUN ?",
    "SSSOD ?",
    "SSINFFRM ?",
)

# Queries for signal information that the receiver doesn't push reliably.
INFO_QUERIES: tuple[str, ...] = (
    "SSINFSIGRES ?",
    "SSINFAISFSV ?",
    "SSINFAISSIG ?",
)

INFO_POLL_INTERVAL = 60
