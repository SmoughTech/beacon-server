"""Sim-layout API: consolidated event layout for Beacon desktop sim."""

from __future__ import annotations

import base64
from typing import Any, Callable

from fastapi import APIRouter, HTTPException

from access_control import barrier_row_to_dict, enrich_scanner_gate_dict, sim_location_row_to_dict, zone_row_to_dict
from geometry import GRID_H, GRID_W, build_scanner_graph, navmesh_to_bytes, rasterize_walls


SIM_LAYOUT_SCHEMA_VERSION = 1


def register_sim_layout(
    app,
    get_connection: Callable,
    now_iso: Callable[[], str],
    get_event_config: Callable[[str], dict[str, Any]],
    scanner_gate_row_to_dict: Callable[[Any], dict[str, Any]],
    calibration_anchor_row_to_dict: Callable[[Any], dict[str, Any]],
) -> None:
    router = APIRouter()

    @router.get("/events/{event_id}/sim-layout")
    def get_sim_layout(event_id: str):
        try:
            event = get_event_config(event_id)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=404, detail="Event not found") from exc

        with get_connection() as conn:
            barrier_rows = conn.execute(
                """
                SELECT * FROM access_barriers
                WHERE event_id = ?
                ORDER BY name COLLATE NOCASE ASC
                """,
                (event_id,),
            ).fetchall()
            zone_rows = conn.execute(
                """
                SELECT * FROM access_zones
                WHERE event_id = ?
                ORDER BY name COLLATE NOCASE ASC
                """,
                (event_id,),
            ).fetchall()
            gate_rows = conn.execute(
                """
                SELECT * FROM wrstops_gates
                WHERE event_id = ?
                ORDER BY name COLLATE NOCASE ASC
                """,
                (event_id,),
            ).fetchall()
            anchor_rows = conn.execute(
                """
                SELECT * FROM map_calibration_anchors
                WHERE event_id = ?
                ORDER BY created_at ASC
                """,
                (event_id,),
            ).fetchall()
            sim_location_rows = conn.execute(
                """
                SELECT * FROM sim_locations
                WHERE event_id = ?
                ORDER BY name COLLATE NOCASE ASC
                """,
                (event_id,),
            ).fetchall()

        barriers = [barrier_row_to_dict(row) for row in barrier_rows]
        zones = [zone_row_to_dict(row) for row in zone_rows]
        gates = [scanner_gate_row_to_dict(row) for row in gate_rows]
        anchors = [calibration_anchor_row_to_dict(row) for row in anchor_rows]
        sim_locations = [sim_location_row_to_dict(row) for row in sim_location_rows]

        grid = rasterize_walls(barriers, gates)
        navmesh_raw = navmesh_to_bytes(grid)
        scanner_graph = build_scanner_graph(zones, gates)

        return {
            "schema_version": SIM_LAYOUT_SCHEMA_VERSION,
            "event_id": event_id,
            "event_name": event.get("name", event_id),
            "map_url": event.get("map_url"),
            "coordinate_system": {
                "space": "normalized",
                "origin": "top_left",
                "x_range": [0.0, 1.0],
                "y_range": [0.0, 1.0],
                "navmesh_width": GRID_W,
                "navmesh_height": GRID_H,
            },
            "barriers": barriers,
            "zones": zones,
            "scanners": gates,
            "gates": gates,
            "calibration_anchors": anchors,
            "sim_locations": sim_locations,
            "navmesh": {
                "encoding": "base64",
                "width": GRID_W,
                "height": GRID_H,
                "walkable_value": 0,
                "blocked_value": 1,
                "data": base64.b64encode(navmesh_raw).decode("ascii"),
            },
            "scanner_graph": scanner_graph,
            "portal_graph": scanner_graph,
            "generated_at": now_iso(),
        }

    app.include_router(router)
