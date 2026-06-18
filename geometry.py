"""Navmesh rasterization for Beacon sim-layout (ported from access-control.js)."""

from __future__ import annotations

import math
from typing import Any, Callable, Iterator

GRID_W = 400
GRID_H = 225
PORTAL_SNAP_DIST = 0.011
PORTAL_VIRTUAL_WALL_EXTEND = 0.006
PORTAL_GAP_HALF_WIDTH = 0.014


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


def gate_on_barrier(gate: dict[str, Any]) -> bool:
    return bool(gate.get("barrier_id")) and gate.get("barrier_segment_index") is not None


def portal_fence_line_heading(gate: dict[str, Any]) -> float:
    fence = gate_fence_heading(gate)
    if gate_on_barrier(gate):
        return (fence + 90.0) % 360
    return fence


def get_portal_snap_pair(gate: dict[str, Any]) -> dict[str, Any] | None:
    cx = gate.get("map_x", gate.get("mapX"))
    cy = gate.get("map_y", gate.get("mapY"))
    if cx is None or cy is None:
        return None
    heading = portal_fence_line_heading(gate)
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


def iter_barrier_segments(barrier: dict[str, Any]) -> Iterator[tuple[int, dict[str, Any], dict[str, Any]]]:
    pts = barrier.get("points") or []
    if len(pts) < 2:
        return
    closed = bool(barrier.get("closed"))
    seg_count = len(pts) - 1
    if closed and len(pts) >= 3:
        seg_count += 1
    for i in range(seg_count):
        yield i, pts[i], pts[(i + 1) % len(pts)]


def project_point_on_segment(
    a: dict[str, Any],
    b: dict[str, Any],
    px: float,
    py: float,
) -> tuple[float, float, float, float]:
    ax, ay = float(a["x"]), float(a["y"])
    bx, by = float(b["x"]), float(b["y"])
    dx, dy = bx - ax, by - ay
    len2 = dx * dx + dy * dy
    if len2 < 1e-12:
        dist = math.hypot(px - ax, py - ay)
        return 0.0, ax, ay, dist
    t = ((px - ax) * dx + (py - ay) * dy) / len2
    t = max(0.0, min(1.0, t))
    mx = ax + dx * t
    my = ay + dy * t
    dist = math.hypot(px - mx, py - my)
    return t, mx, my, dist


def segment_tangent_heading_deg(a: dict[str, Any], b: dict[str, Any]) -> float:
    dx = float(b["x"]) - float(a["x"])
    dy = float(b["y"]) - float(a["y"])
    return math.degrees(math.atan2(dy, dx)) % 360


def fence_crossing_heading_deg(a: dict[str, Any], b: dict[str, Any]) -> float:
    return (segment_tangent_heading_deg(a, b) + 90.0) % 360


def draw_norm_segment_with_gaps(
    grid: list[list[int]],
    a: dict[str, Any],
    b: dict[str, Any],
    gaps: list[tuple[float, float]],
    mark: Callable[[int, int], None],
) -> None:
    ax, ay = float(a["x"]), float(a["y"])
    bx, by = float(b["x"]), float(b["y"])
    seg_len = math.hypot(bx - ax, by - ay)
    if seg_len < 1e-9:
        return

    intervals = [(0.0, 1.0)]
    for t_center, half_width in sorted(gaps):
        half_t = half_width / seg_len
        gap_lo = max(0.0, t_center - half_t)
        gap_hi = min(1.0, t_center + half_t)
        new_intervals: list[tuple[float, float]] = []
        for lo, hi in intervals:
            if hi <= gap_lo or lo >= gap_hi:
                new_intervals.append((lo, hi))
            else:
                if lo < gap_lo:
                    new_intervals.append((lo, gap_lo))
                if hi > gap_hi:
                    new_intervals.append((gap_hi, hi))
        intervals = new_intervals

    for lo, hi in intervals:
        if hi - lo < 1e-6:
            continue
        x0 = ax + (bx - ax) * lo
        y0 = ay + (by - ay) * lo
        x1 = ax + (bx - ax) * hi
        y1 = ay + (by - ay) * hi
        ga = grid_from_norm(x0, y0)
        gb = grid_from_norm(x1, y1)
        draw_grid_line(grid, ga[0], ga[1], gb[0], gb[1], mark)


def gate_segment_gaps(gate: dict[str, Any], a: dict[str, Any], b: dict[str, Any]) -> list[tuple[float, float]]:
    cx = gate.get("map_x", gate.get("mapX"))
    cy = gate.get("map_y", gate.get("mapY"))
    if cx is None or cy is None:
        return []
    seg_t = gate.get("barrier_segment_t")
    if seg_t is None:
        seg_t, _, _, _ = project_point_on_segment(a, b, float(cx), float(cy))
    return [(float(seg_t), PORTAL_GAP_HALF_WIDTH)]


def collect_gate_attachments(
    gates: list[dict[str, Any]],
) -> dict[tuple[str, int], list[dict[str, Any]]]:
    attachments: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for gate in gates:
        barrier_id = gate.get("barrier_id")
        seg_idx = gate.get("barrier_segment_index")
        if not barrier_id or seg_idx is None:
            continue
        key = (str(barrier_id), int(seg_idx))
        attachments.setdefault(key, []).append(gate)
    return attachments


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

    attachments = collect_gate_attachments(gates)

    for barrier in barriers:
        barrier_id = str(barrier.get("id", ""))
        for seg_idx, a, b in iter_barrier_segments(barrier):
            seg_gates = attachments.get((barrier_id, seg_idx), [])
            gaps: list[tuple[float, float]] = []
            for gate in seg_gates:
                gaps.extend(gate_segment_gaps(gate, a, b))
            draw_norm_segment_with_gaps(grid, a, b, gaps, mark)

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
                    "via_portal": via,
                    "allowed_classes": allowed,
                }
            )

        if direction in ("bidirectional", "a_to_b"):
            add_edge(zone_a or "outside", zone_b or "outside", gate_id)
        if direction in ("bidirectional", "b_to_a"):
            add_edge(zone_b or "outside", zone_a or "outside", gate_id)

    return {"nodes": nodes, "edges": edges}


build_portal_graph = build_scanner_graph
