"""Navmesh rasterization for Beacon sim-layout (ported from access-control.js)."""

from __future__ import annotations

import math
from typing import Any, Callable

GRID_W = 400
GRID_H = 225
PORTAL_SNAP_DIST = 0.011
PORTAL_VIRTUAL_WALL_EXTEND = 0.006


def grid_from_norm(x: float, y: float) -> tuple[int, int]:
    gx = max(0, min(GRID_W - 1, round(x * (GRID_W - 1))))
    gy = max(0, min(GRID_H - 1, round(y * (GRID_H - 1))))
    return gx, gy


def norm_from_grid(gx: int, gy: int) -> tuple[float, float]:
    return gx / (GRID_W - 1), gy / (GRID_H - 1)


def heading_unit_rad(deg: float) -> tuple[float, float]:
    rad = math.radians(deg)
    return math.cos(rad), math.sin(rad)


def gate_fence_heading(gate: dict[str, Any]) -> float:
    raw = gate.get("fence_heading_deg", gate.get("fenceHeadingDeg", 0))
    return float(raw) % 360


def get_portal_snap_pair(gate: dict[str, Any]) -> dict[str, Any] | None:
    cx = gate.get("map_x", gate.get("mapX"))
    cy = gate.get("map_y", gate.get("mapY"))
    if cx is None or cy is None:
        return None
    heading = gate_fence_heading(gate)
    ux, uy = heading_unit_rad(heading)
    cx_f, cy_f = float(cx), float(cy)
    return {
        "gate_id": gate.get("id"),
        "center": {"x": cx_f, "y": cy_f},
        "heading": heading,
        "a": {"x": cx_f - ux * PORTAL_SNAP_DIST, "y": cy_f - uy * PORTAL_SNAP_DIST, "side": "a"},
        "b": {"x": cx_f + ux * PORTAL_SNAP_DIST, "y": cy_f + uy * PORTAL_SNAP_DIST, "side": "b"},
    }


def draw_grid_line(
    grid: list[list[int]],
    x0: int,
    y0: int,
    x1: int,
    y1: int,
    mark: Callable[[int, int], None],
) -> None:
    dx = abs(x1 - x0)
    dy = abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx - dy
    while True:
        mark(x0, y0)
        for oy in (-1, 0, 1):
            for ox in (-1, 0, 1):
                mark(x0 + ox, y0 + oy)
        if x0 == x1 and y0 == y1:
            break
        e2 = 2 * err
        if e2 > -dy:
            err -= dy
            x0 += sx
        if e2 < dx:
            err += dx
            y0 += sy


def add_portal_virtual_wall(grid: list[list[int]], gate: dict[str, Any]) -> None:
    pair = get_portal_snap_pair(gate)
    if pair is None:
        return

    def mark(gx: int, gy: int) -> None:
        if 0 <= gx < GRID_W and 0 <= gy < GRID_H:
            grid[gy][gx] = 1

    ux, uy = heading_unit_rad(pair["heading"])
    ax = pair["a"]["x"] - ux * PORTAL_VIRTUAL_WALL_EXTEND
    ay = pair["a"]["y"] - uy * PORTAL_VIRTUAL_WALL_EXTEND
    bx = pair["b"]["x"] + ux * PORTAL_VIRTUAL_WALL_EXTEND
    by = pair["b"]["y"] + uy * PORTAL_VIRTUAL_WALL_EXTEND
    a = grid_from_norm(ax, ay)
    b = grid_from_norm(bx, by)
    draw_grid_line(grid, a[0], a[1], b[0], b[1], mark)


def rasterize_walls(
    barriers: list[dict[str, Any]],
    gates: list[dict[str, Any]],
) -> list[list[int]]:
    grid = [[0 for _ in range(GRID_W)] for _ in range(GRID_H)]

    def mark(gx: int, gy: int) -> None:
        if 0 <= gx < GRID_W and 0 <= gy < GRID_H:
            grid[gy][gx] = 1

    for barrier in barriers:
        pts = barrier.get("points") or []
        for i in range(1, len(pts)):
            a = grid_from_norm(float(pts[i - 1]["x"]), float(pts[i - 1]["y"]))
            b = grid_from_norm(float(pts[i]["x"]), float(pts[i]["y"]))
            draw_grid_line(grid, a[0], a[1], b[0], b[1], mark)

    for gate in gates:
        add_portal_virtual_wall(grid, gate)

    return grid


def navmesh_to_bytes(grid: list[list[int]]) -> bytes:
    """Return walkability: 0 = walkable, 1 = blocked (wall)."""
    out = bytearray(GRID_W * GRID_H)
    for gy in range(GRID_H):
        for gx in range(GRID_W):
            out[gy * GRID_W + gx] = 1 if grid[gy][gx] else 0
    return bytes(out)


def build_scanner_graph(
    zones: list[dict[str, Any]],
    gates: list[dict[str, Any]],
) -> dict[str, Any]:
    zone_by_id = {z["id"]: z for z in zones}
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    nodes.append({"id": "outside", "kind": "outside", "label": "Outside"})

    for zone in zones:
        poly = zone.get("polygon") or []
        cx = sum(p["x"] for p in poly) / len(poly) if poly else 0.5
        cy = sum(p["y"] for p in poly) / len(poly) if poly else 0.5
        nodes.append(
            {
                "id": zone["id"],
                "kind": "zone",
                "label": zone.get("name", zone["id"]),
                "zone_class": zone.get("zone_class", "ga"),
                "centroid": {"x": cx, "y": cy},
            }
        )

    for gate in gates:
        pair = get_portal_snap_pair(gate)
        if pair is None:
            continue
        gate_id = gate["id"]
        nodes.append(
            {
                "id": gate_id,
                "kind": "scanner",
                "label": gate.get("name", gate_id),
                "map_x": pair["center"]["x"],
                "map_y": pair["center"]["y"],
                "device_type": gate.get("device_type", "scanner"),
            }
        )

        zone_a = gate.get("zone_a_id")
        zone_b = gate.get("zone_b_id")
        allowed = gate.get("allowed_classes") or []
        direction = gate.get("direction") or "bidirectional"

        def add_edge(from_id: str, to_id: str, via: str) -> None:
            if not from_id or not to_id:
                return
            if from_id not in zone_by_id and from_id != "outside":
                return
            if to_id not in zone_by_id and to_id != "outside":
                return
            edges.append(
                {
                    "from": from_id,
                    "to": to_id,
                    "via_scanner": via,
                    "allowed_classes": allowed,
                }
            )

        if direction in ("bidirectional", "a_to_b"):
            add_edge(zone_a or "outside", zone_b or "outside", gate_id)
        if direction in ("bidirectional", "b_to_a"):
            add_edge(zone_b or "outside", zone_a or "outside", gate_id)

    return {"nodes": nodes, "edges": edges}


build_portal_graph = build_scanner_graph
