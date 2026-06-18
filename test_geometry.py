"""Tests for geometry navmesh rasterization."""

import base64

from geometry import (
    GRID_H,
    GRID_W,
    SURFACE_AREA,
    SURFACE_BLOCKED,
    SURFACE_PATH,
    SURFACE_WALKABLE,
    build_scanner_graph,
    build_surface_grid,
    build_surface_payload,
    grid_from_norm,
    navmesh_to_bytes,
    rasterize_walls,
    surface_to_bytes,
)


def test_empty_layout_walkable():
    grid = rasterize_walls([], [])
    raw = navmesh_to_bytes(grid)
    assert len(raw) == GRID_W * GRID_H
    assert all(b == 0 for b in raw)


def test_barrier_blocks_cells():
    barriers = [
        {
            "id": "b1",
            "points": [{"x": 0.2, "y": 0.5}, {"x": 0.8, "y": 0.5}],
        }
    ]
    grid = rasterize_walls(barriers, [])
    raw = navmesh_to_bytes(grid)
    assert any(b == 1 for b in raw)


def test_closed_barrier_blocks_closing_segment():
    barriers = [
        {
            "id": "b1",
            "closed": True,
            "points": [
                {"x": 0.2, "y": 0.2},
                {"x": 0.8, "y": 0.2},
                {"x": 0.8, "y": 0.8},
            ],
        }
    ]
    grid = rasterize_walls(barriers, [])
    gx, gy = grid_from_norm(0.5, 0.2)
    assert grid[gy][gx] == 1

def test_tile_barrier_blocks_cells():
    barriers = [
        {
            "id": "b1",
            "tiles": [[100, 50], [101, 50], [102, 50]],
        }
    ]
    grid = rasterize_walls(barriers, [])
    assert grid[50][100] == 1
    assert grid[50][101] == 1
    assert grid[50][102] == 1

    barriers = [
        {
            "id": "b1",
            "points": [{"x": 0.2, "y": 0.5}, {"x": 0.8, "y": 0.5}],
        }
    ]
    gates = [
        {
            "id": "gate_1",
            "map_x": 0.5,
            "map_y": 0.5,
            "fence_heading_deg": 0,
            "barrier_id": "b1",
            "barrier_segment_index": 0,
            "barrier_segment_t": 0.5,
        }
    ]
    grid = rasterize_walls(barriers, gates)
    gx, gy = grid_from_norm(0.49, 0.5)
    assert grid[gy][gx] == 0
    cx, cy = grid_from_norm(0.5, 0.5)
    assert grid[cy][cx] == 1


def test_scanner_graph():
    zones = [
        {
            "id": "zone_ga",
            "name": "GA",
            "zone_class": "ga",
            "polygon": [{"x": 0.1, "y": 0.1}, {"x": 0.9, "y": 0.1}, {"x": 0.9, "y": 0.9}],
        },
        {
            "id": "zone_vip",
            "name": "VIP",
            "zone_class": "vip",
            "polygon": [{"x": 0.5, "y": 0.1}, {"x": 0.9, "y": 0.1}, {"x": 0.9, "y": 0.5}],
        },
    ]
    gates = [
        {
            "id": "gate_1",
            "name": "Main Scanner",
            "map_x": 0.5,
            "map_y": 0.5,
            "fence_heading_deg": 0,
            "zone_a_id": "zone_ga",
            "zone_b_id": "zone_vip",
            "allowed_classes": ["ga", "vip"],
            "direction": "bidirectional",
        }
    ]
    graph = build_scanner_graph(zones, gates)
    assert any(n["kind"] == "scanner" for n in graph["nodes"])
    assert len(graph["edges"]) >= 2


def test_surface_grid_blocked_and_path():
    barriers = [{"id": "b1", "tiles": [[10, 10]]}]
    paths = [{"id": "p1", "tiles": [[20, 20], [21, 20], [22, 20]]}]
    grid = build_surface_grid(barriers, [], [], paths)
    assert grid[10][10] == SURFACE_BLOCKED
    assert grid[20][20] == SURFACE_PATH
    assert grid[20][21] == SURFACE_PATH
    assert grid[50][50] == SURFACE_WALKABLE


def test_surface_grid_area_from_zone():
    zones = [
        {
            "id": "zone_ga",
            "polygon": [
                {"x": 0.45, "y": 0.45},
                {"x": 0.55, "y": 0.45},
                {"x": 0.55, "y": 0.55},
                {"x": 0.45, "y": 0.55},
            ],
        }
    ]
    grid = build_surface_grid([], [], zones, [])
    gx, gy = grid_from_norm(0.5, 0.5)
    assert grid[gy][gx] == SURFACE_AREA


def test_surface_path_overrides_area():
    zones = [
        {
            "id": "zone_ga",
            "polygon": [
                {"x": 0.45, "y": 0.45},
                {"x": 0.55, "y": 0.45},
                {"x": 0.55, "y": 0.55},
                {"x": 0.45, "y": 0.55},
            ],
        }
    ]
    gx, gy = grid_from_norm(0.5, 0.5)
    paths = [{"id": "p1", "tiles": [[gx, gy]]}]
    grid = build_surface_grid([], [], zones, paths)
    assert grid[gy][gx] == SURFACE_PATH


def test_surface_payload_encoding():
    grid = build_surface_grid([], [], [], [])
    payload = build_surface_payload(grid)
    raw = base64.b64decode(payload["data"])
    assert len(raw) == GRID_W * GRID_H
    assert payload["values"]["path"] == SURFACE_PATH
    assert surface_to_bytes(grid) == raw
