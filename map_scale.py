"""Per-event real-world map extent and derived grid / marker scale."""

from __future__ import annotations

from typing import Any

from tile_grid import TILE_COLS, TILE_ROWS, build_coordinate_system

DEFAULT_MAP_WIDTH_FT = 800.0
DEFAULT_MAP_HEIGHT_FT = 450.0
DEFAULT_PERSON_HEIGHT_FT = 5.75
FESTIVAL_MAP_WIDTH_FT = 800.0
FESTIVAL_MAP_HEIGHT_FT = 450.0
HOUSE_MAP_WIDTH_FT = 60.0
HOUSE_MAP_HEIGHT_FT = 40.0
SCANNER_WIDTH_FT = 3.0
DEFAULT_SCANNER_SCALE_PCT = 72


def _float(value: Any, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if parsed <= 0:
        return default
    return parsed


def map_extent_from_event(event: dict[str, Any]) -> tuple[float, float]:
    return (
        _float(event.get("map_width_ft"), DEFAULT_MAP_WIDTH_FT),
        _float(event.get("map_height_ft"), DEFAULT_MAP_HEIGHT_FT),
    )


def tile_size_ft_for_map(map_width_ft: float) -> float:
    return map_width_ft / TILE_COLS


def scanner_scale_percent(map_width_ft: float) -> int:
    """Scanner marker size relative to festival default (3 ft gate @ 800 ft map)."""
    pct = DEFAULT_SCANNER_SCALE_PCT * (DEFAULT_MAP_WIDTH_FT / max(map_width_ft, 1.0))
    return int(max(40, min(150, round(pct))))


def person_shoulder_norm(map_width_ft: float) -> float:
    return 1.5 / max(map_width_ft, 1.0)


def build_coordinate_system_for_event(event: dict[str, Any]) -> dict[str, Any]:
    map_width_ft, map_height_ft = map_extent_from_event(event)
    cs = build_coordinate_system()
    cs["map_width_ft"] = map_width_ft
    cs["map_height_ft"] = map_height_ft
    cs["tile_size_ft"] = tile_size_ft_for_map(map_width_ft)
    cs["tile_height_ft"] = map_height_ft / TILE_ROWS
    cs["scanner_width_ft"] = SCANNER_WIDTH_FT
    cs["scanner_scale_percent"] = scanner_scale_percent(map_width_ft)
    cs["person_height_ft"] = _float(event.get("person_height_ft"), DEFAULT_PERSON_HEIGHT_FT)
    if event.get("person_map_x") is not None:
        cs["person_map_x"] = float(event["person_map_x"])
    if event.get("person_map_y") is not None:
        cs["person_map_y"] = float(event["person_map_y"])
    if event.get("person_height_norm") is not None:
        cs["person_height_norm"] = float(event["person_height_norm"])
    return cs


def scale_from_person_calibration(
    person_height_ft: float,
    person_height_norm: float,
    map_aspect: float = 16 / 9,
) -> tuple[float, float]:
    """Derive map extent when a person of known height spans person_height_norm of map Y."""
    height_norm = max(person_height_norm, 1e-6)
    map_height_ft = person_height_ft / height_norm
    map_width_ft = map_height_ft * map_aspect
    return map_width_ft, map_height_ft
