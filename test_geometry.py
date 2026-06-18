"""Tests for geometry navmesh rasterization."""

from geometry import (
    GRID_H,
    GRID_W,
    build_scanner_graph,
    grid_from_norm,
    navmesh_to_bytes,
    rasterize_walls,
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


def test_scanner_on_barrier_creates_walkable_gap():
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
