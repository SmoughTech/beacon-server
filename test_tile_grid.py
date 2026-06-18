"""Tests for tile_grid vertex coordinate system."""

from tile_grid import (
    TILE_COLS,
    TILE_ROWS,
    TILE_SIZE_FT,
    TRIANGLES_PER_TILE,
    VERTEX_COLS,
    VERTEX_ROWS,
    build_coordinate_system,
    grid_from_norm,
    is_valid_barrier_segment,
    norm_from_grid,
    norm_from_vertex,
    snap_placement_anchor,
    tile_from_norm,
    vertex_from_norm,
)


def test_tile_constants():
    assert TILE_SIZE_FT == 2.0
    assert TILE_COLS == 400
    assert TILE_ROWS == 225
    assert VERTEX_COLS == TILE_COLS + 1
    assert VERTEX_ROWS == TILE_ROWS + 1
    assert TRIANGLES_PER_TILE == 4


def test_vertex_round_trip_center():
    vx, vy = vertex_from_norm(0.5, 0.5)
    nx, ny = norm_from_vertex(vx, vy)
    assert abs(nx - 0.5) < 0.01
    assert abs(ny - 0.5) < 0.01


def test_valid_barrier_segments():
    a = {"x": 0.25, "y": 0.25}
    b_h = {"x": 0.5, "y": 0.25}
    b_v = {"x": 0.25, "y": 0.5}
    b_d = {"x": 0.5, "y": 0.5}
    assert is_valid_barrier_segment(a, b_h)
    assert is_valid_barrier_segment(a, b_v)
    assert is_valid_barrier_segment(a, b_d)
    assert not is_valid_barrier_segment(a, {"x": 0.6, "y": 0.3})


def test_coordinate_system_export():
    cs = build_coordinate_system()
    assert cs["space"] == "vertex_grid"
    assert cs["tile_size_ft"] == 2.0
    assert cs["snap_mode"] == "vertices"
    assert cs["navmesh_width"] == TILE_COLS


def test_grid_cell_from_norm():
    tx, ty = tile_from_norm(0.5, 0.5)
    assert 0 <= tx < TILE_COLS
    assert 0 <= ty < TILE_ROWS
    cx, cy = norm_from_grid(tx, ty)
    assert 0.0 < cx < 1.0
    assert 0.0 < cy < 1.0
    assert grid_from_norm(cx, cy) == (tx, ty)


def test_placement_snap_vertex():
    anchor = snap_placement_anchor(0.5, 0.5)
    assert anchor["snap_kind"] == "vertex"
