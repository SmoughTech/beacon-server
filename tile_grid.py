"""Canonical 2ft tile grid with 4-triangle subdivision per tile.

Each tile is 2ft × 2ft. Vertices sit on grid-line intersections (tile corners).
Every tile is split into four triangles by both diagonals (X through the center).

Normalized coordinates map vertex (vx, vy) → (vx / TILE_COLS, vy / TILE_ROWS).
Navmesh cells are one per tile (TILE_COLS × TILE_ROWS); pathfinding upgrades to
triangle-edge routing in a later phase.
"""

from __future__ import annotations

import math
from typing import Any

TILE_SIZE_FT = 2.0
TILE_COLS = 400
TILE_ROWS = 225
VERTEX_COLS = TILE_COLS + 1
VERTEX_ROWS = TILE_ROWS + 1
TRIANGLES_PER_TILE = 4

# Legacy aliases used by geometry navmesh rasterization.
GRID_W = TILE_COLS
GRID_H = TILE_ROWS

VERTEX_SNAP_RADIUS_NORM = 0.012
PLACEMENT_SNAP_RADIUS_NORM = 0.018


def vertex_from_norm(x: float, y: float) -> tuple[int, int]:
    vx = max(0, min(VERTEX_COLS - 1, round(x * TILE_COLS)))
    vy = max(0, min(VERTEX_ROWS - 1, round(y * TILE_ROWS)))
    return vx, vy


def norm_from_vertex(vx: int, vy: int) -> tuple[float, float]:
    return vx / TILE_COLS, vy / TILE_ROWS


def tile_from_norm(x: float, y: float) -> tuple[int, int]:
    tx = max(0, min(TILE_COLS - 1, int(x * TILE_COLS)))
    ty = max(0, min(TILE_ROWS - 1, int(y * TILE_ROWS)))
    return tx, ty


def norm_from_tile_center(tx: int, ty: int) -> tuple[float, float]:
    return (tx + 0.5) / TILE_COLS, (ty + 0.5) / TILE_ROWS


def grid_from_norm(x: float, y: float) -> tuple[int, int]:
    """Navmesh cell index for a normalized point (one cell per tile)."""
    return tile_from_norm(x, y)


def norm_from_grid(gx: int, gy: int) -> tuple[float, float]:
    """Center of navmesh cell in normalized space."""
    return norm_from_tile_center(gx, gy)


def tile_center_norm(tx: int, ty: int) -> tuple[float, float]:
    return norm_from_tile_center(tx, ty)


def tile_corner_norm(tx: int, ty: int, corner: str) -> tuple[float, float]:
    if corner == "tl":
        return norm_from_vertex(tx, ty)
    if corner == "tr":
        return norm_from_vertex(tx + 1, ty)
    if corner == "br":
        return norm_from_vertex(tx + 1, ty + 1)
    if corner == "bl":
        return norm_from_vertex(tx, ty + 1)
    raise ValueError(f"unknown corner {corner!r}")


def tile_triangle_centers(tx: int, ty: int) -> list[tuple[float, float]]:
    """Four triangle centroids inside tile (tx, ty) for debug / placement hints."""
    tl = norm_from_vertex(tx, ty)
    tr = norm_from_vertex(tx + 1, ty)
    br = norm_from_vertex(tx + 1, ty + 1)
    bl = norm_from_vertex(tx, ty + 1)
    cx = (tl[0] + tr[0] + br[0] + bl[0]) / 4.0
    cy = (tl[1] + tr[1] + br[1] + bl[1]) / 4.0
    return [
        ((tl[0] + tr[0] + cx) / 3.0, (tl[1] + tr[1] + cy) / 3.0),
        ((tr[0] + br[0] + cx) / 3.0, (tr[1] + br[1] + cy) / 3.0),
        ((br[0] + bl[0] + cx) / 3.0, (br[1] + bl[1] + cy) / 3.0),
        ((bl[0] + tl[0] + cx) / 3.0, (bl[1] + tl[1] + cy) / 3.0),
    ]


def is_axis_aligned_segment(a: dict[str, Any], b: dict[str, Any], tol: float = 1e-6) -> bool:
    return abs(a["x"] - b["x"]) < tol or abs(a["y"] - b["y"]) < tol


def is_diagonal_segment(a: dict[str, Any], b: dict[str, Any], tol: float = 1e-6) -> bool:
    avx, avy = vertex_from_norm(float(a["x"]), float(a["y"]))
    bvx, bvy = vertex_from_norm(float(b["x"]), float(b["y"]))
    return abs(abs(avx - bvx) - abs(avy - bvy)) == 0 and (avx != bvx and avy != bvy)


def is_valid_barrier_segment(a: dict[str, Any], b: dict[str, Any]) -> bool:
    avx, avy = vertex_from_norm(float(a["x"]), float(a["y"]))
    bvx, bvy = vertex_from_norm(float(b["x"]), float(b["y"]))
    if avx == bvx and avy == bvy:
        return False
    dvx = abs(avx - bvx)
    dvy = abs(avy - bvy)
    return (dvx == 0 and dvy > 0) or (dvy == 0 and dvx > 0) or (dvx == dvy)


def iter_vertex_line(
    ax: int, ay: int, bx: int, by: int
) -> list[tuple[int, int]]:
    """Bresenham vertex steps along H/V/diagonal grid lines."""
    points: list[tuple[int, int]] = []
    x0, y0, x1, y1 = ax, ay, bx, by
    dx = abs(x1 - x0)
    dy = abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx - dy
    while True:
        points.append((x0, y0))
        if x0 == x1 and y0 == y1:
            break
        e2 = 2 * err
        if e2 > -dy:
            err -= dy
            x0 += sx
        if e2 < dx:
            err += dx
            y0 += sy
    return points


def snap_placement_anchor(
    x: float, y: float, radius_norm: float = PLACEMENT_SNAP_RADIUS_NORM
) -> dict[str, Any]:
    """Snap to nearest vertex or H/V edge midpoint (for scanners, tents, POIs)."""
    best: dict[str, Any] | None = None
    best_dist = radius_norm

    for vx in range(VERTEX_COLS):
        nx = vx / TILE_COLS
        for vy in range(VERTEX_ROWS):
            ny = vy / TILE_ROWS
            d = math.hypot(x - nx, y - ny)
            if d < best_dist:
                best_dist = d
                best = {"x": nx, "y": ny, "snap_kind": "vertex", "vx": vx, "vy": vy}

    for tx in range(TILE_COLS):
        mid_x = (tx + 0.5) / TILE_COLS
        for vy in range(VERTEX_ROWS):
            ny = vy / TILE_ROWS
            d = math.hypot(x - mid_x, y - ny)
            if d < best_dist:
                best_dist = d
                best = {
                    "x": mid_x,
                    "y": ny,
                    "snap_kind": "h_edge",
                    "tx": tx,
                    "vy": vy,
                }

    for vx in range(VERTEX_COLS):
        nx = vx / TILE_COLS
        for ty in range(TILE_ROWS):
            mid_y = (ty + 0.5) / TILE_ROWS
            d = math.hypot(x - nx, y - mid_y)
            if d < best_dist:
                best_dist = d
                best = {
                    "x": nx,
                    "y": mid_y,
                    "snap_kind": "v_edge",
                    "vx": vx,
                    "ty": ty,
                }

    if best is None:
        vx, vy = vertex_from_norm(x, y)
        nx, ny = norm_from_vertex(vx, vy)
        return {"x": nx, "y": ny, "snap_kind": "vertex", "vx": vx, "vy": vy, "forced": True}
    return best


def build_coordinate_system() -> dict[str, Any]:
    return {
        "space": "vertex_grid",
        "origin": "top_left",
        "x_range": [0.0, 1.0],
        "y_range": [0.0, 1.0],
        "tile_cols": TILE_COLS,
        "tile_rows": TILE_ROWS,
        "tile_size_ft": TILE_SIZE_FT,
        "vertex_cols": VERTEX_COLS,
        "vertex_rows": VERTEX_ROWS,
        "triangles_per_tile": TRIANGLES_PER_TILE,
        "snap_mode": "vertices",
        "navmesh_width": TILE_COLS,
        "navmesh_height": TILE_ROWS,
        "tile_width": TILE_COLS,
        "tile_height": TILE_ROWS,
        "tile_space": "vertex_grid",
    }
