"""Access control layout: barriers, zones, and portal rules for Beacon Dash."""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Callable, List, Optional
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

ZONE_CLASSES = ("ga", "vip", "staff", "backstage", "vendor")
BARRIER_TYPES = ("fence", "barricade", "wall", "rope")

ZONE_COLORS = {
    "ga": "rgba(76,175,80,0.38)",
    "vip": "rgba(255,193,7,0.40)",
    "staff": "rgba(66,165,245,0.40)",
    "backstage": "rgba(171,71,188,0.40)",
    "vendor": "rgba(255,152,0,0.38)",
}


class MapPoint(BaseModel):
    x: float = Field(ge=0.0, le=1.0)
    y: float = Field(ge=0.0, le=1.0)


class AccessBarrierCreate(BaseModel):
    name: str = Field(default="Barrier", min_length=1, max_length=120)
    barrier_type: str = Field(default="fence", max_length=40)
    points: List[MapPoint] = Field(min_length=2)
    updated_by: Optional[str] = "dash_access"


class AccessBarrierUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    barrier_type: Optional[str] = Field(default=None, max_length=40)
    points: Optional[List[MapPoint]] = Field(default=None, min_length=2)
    updated_by: Optional[str] = "dash_access"


class AccessZoneCreate(BaseModel):
    name: str = Field(default="Zone", min_length=1, max_length=120)
    zone_class: str = Field(default="ga", max_length=40)
    polygon: List[MapPoint] = Field(min_length=3)
    fill_color: Optional[str] = Field(default=None, max_length=80)
    updated_by: Optional[str] = "dash_access"


class AccessZoneUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    zone_class: Optional[str] = Field(default=None, max_length=40)
    polygon: Optional[List[MapPoint]] = Field(default=None, min_length=3)
    fill_color: Optional[str] = Field(default=None, max_length=80)
    updated_by: Optional[str] = "dash_access"


class GatePortalAccessUpdate(BaseModel):
    zone_a_id: Optional[str] = Field(default=None, max_length=80)
    zone_b_id: Optional[str] = Field(default=None, max_length=80)
    allowed_classes: List[str] = Field(default_factory=list)
    direction: str = Field(default="bidirectional", max_length=40)
    barrier_id: Optional[str] = Field(default=None, max_length=80)
    updated_by: Optional[str] = "dash_access"


def normalize_zone_class(value: Optional[str]) -> str:
    raw = (value or "ga").strip().lower()
    if raw not in ZONE_CLASSES:
        raw = "ga"
    return raw


def normalize_barrier_type(value: Optional[str]) -> str:
    raw = (value or "fence").strip().lower()
    if raw not in BARRIER_TYPES:
        raw = "fence"
    return raw


def normalize_direction(value: Optional[str]) -> str:
    raw = (value or "bidirectional").strip().lower()
    if raw not in {"bidirectional", "a_to_b", "b_to_a"}:
        raw = "bidirectional"
    return raw


def resolve_fill_color(zone_class: str, requested: Optional[str]) -> str:
    if requested:
        cleaned = requested.strip()
        if cleaned:
            lowered = cleaned.lower()
            if lowered.startswith("#") and len(cleaned) in {4, 7, 9}:
                return cleaned
            if lowered.startswith("rgba(") and lowered.endswith(")"):
                return cleaned
            if lowered.startswith("rgb(") and lowered.endswith(")"):
                return cleaned
    return ZONE_COLORS.get(normalize_zone_class(zone_class), ZONE_COLORS["ga"])


def _points_to_json(points: List[MapPoint]) -> str:
    return json.dumps([{"x": p.x, "y": p.y} for p in points])


def _json_to_points(raw: Optional[str]) -> list[dict[str, float]]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
        if not isinstance(data, list):
            return []
        out = []
        for item in data:
            if isinstance(item, dict) and "x" in item and "y" in item:
                out.append({"x": float(item["x"]), "y": float(item["y"])})
        return out
    except (TypeError, ValueError, json.JSONDecodeError):
        return []


def barrier_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "event_id": row["event_id"],
        "name": row["name"],
        "barrier_type": row["barrier_type"],
        "points": _json_to_points(row["points_json"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "updated_by": row["updated_by"],
    }


def zone_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    zone_class = row["zone_class"]
    return {
        "id": row["id"],
        "event_id": row["event_id"],
        "name": row["name"],
        "zone_class": zone_class,
        "polygon": _json_to_points(row["polygon_json"]),
        "fill_color": row["fill_color"] or ZONE_COLORS.get(zone_class, ZONE_COLORS["ga"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "updated_by": row["updated_by"],
    }


def enrich_wrstops_gate_dict(row: sqlite3.Row) -> dict[str, Any]:
    keys = row.keys()
    allowed_raw = row["allowed_classes"] if "allowed_classes" in keys else None
    try:
        allowed_classes = json.loads(allowed_raw) if allowed_raw else []
        if not isinstance(allowed_classes, list):
            allowed_classes = []
    except (TypeError, ValueError, json.JSONDecodeError):
        allowed_classes = []

    return {
        "zone_a_id": row["zone_a_id"] if "zone_a_id" in keys else None,
        "zone_b_id": row["zone_b_id"] if "zone_b_id" in keys else None,
        "allowed_classes": allowed_classes,
        "direction": row["direction"] if "direction" in keys else "bidirectional",
        "barrier_id": row["barrier_id"] if "barrier_id" in keys else None,
    }


def init_access_control_db(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS access_barriers (
            id TEXT PRIMARY KEY,
            event_id TEXT NOT NULL,
            name TEXT NOT NULL,
            barrier_type TEXT NOT NULL DEFAULT 'fence',
            points_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            updated_by TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_access_barriers_event_id
        ON access_barriers(event_id)
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS access_zones (
            id TEXT PRIMARY KEY,
            event_id TEXT NOT NULL,
            name TEXT NOT NULL,
            zone_class TEXT NOT NULL DEFAULT 'ga',
            polygon_json TEXT NOT NULL,
            fill_color TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            updated_by TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_access_zones_event_id
        ON access_zones(event_id)
        """
    )

    gate_columns = {row["name"] for row in conn.execute("PRAGMA table_info(wrstops_gates)").fetchall()}
    if "zone_a_id" not in gate_columns:
        conn.execute("ALTER TABLE wrstops_gates ADD COLUMN zone_a_id TEXT")
    if "zone_b_id" not in gate_columns:
        conn.execute("ALTER TABLE wrstops_gates ADD COLUMN zone_b_id TEXT")
    if "allowed_classes" not in gate_columns:
        conn.execute("ALTER TABLE wrstops_gates ADD COLUMN allowed_classes TEXT")
    if "direction" not in gate_columns:
        conn.execute("ALTER TABLE wrstops_gates ADD COLUMN direction TEXT NOT NULL DEFAULT 'bidirectional'")
    if "barrier_id" not in gate_columns:
        conn.execute("ALTER TABLE wrstops_gates ADD COLUMN barrier_id TEXT")


def register_access_control(app, get_connection: Callable, now_iso: Callable[[], str]) -> None:
    router = APIRouter()

    @router.get("/events/{event_id}/access-barriers")
    def list_barriers(event_id: str):
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM access_barriers
                WHERE event_id = ?
                ORDER BY name COLLATE NOCASE ASC
                """,
                (event_id,),
            ).fetchall()
        return [barrier_row_to_dict(row) for row in rows]

    @router.post("/events/{event_id}/access-barriers")
    def create_barrier(event_id: str, payload: AccessBarrierCreate):
        barrier_id = "barrier_" + uuid4().hex[:12]
        timestamp = now_iso()
        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO access_barriers (
                    id, event_id, name, barrier_type, points_json,
                    created_at, updated_at, updated_by
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    barrier_id,
                    event_id,
                    payload.name.strip() or "Barrier",
                    normalize_barrier_type(payload.barrier_type),
                    _points_to_json(payload.points),
                    timestamp,
                    timestamp,
                    payload.updated_by,
                ),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM access_barriers WHERE id = ? AND event_id = ?",
                (barrier_id, event_id),
            ).fetchone()
        return barrier_row_to_dict(row)

    @router.put("/events/{event_id}/access-barriers/{barrier_id}")
    def update_barrier(event_id: str, barrier_id: str, payload: AccessBarrierUpdate):
        with get_connection() as conn:
            existing = conn.execute(
                "SELECT * FROM access_barriers WHERE id = ? AND event_id = ?",
                (barrier_id, event_id),
            ).fetchone()
            if existing is None:
                raise HTTPException(status_code=404, detail="Barrier not found")

            name = payload.name.strip() if payload.name is not None else existing["name"]
            barrier_type = (
                normalize_barrier_type(payload.barrier_type)
                if payload.barrier_type is not None
                else existing["barrier_type"]
            )
            points_json = (
                _points_to_json(payload.points)
                if payload.points is not None
                else existing["points_json"]
            )
            timestamp = now_iso()
            conn.execute(
                """
                UPDATE access_barriers
                SET name = ?, barrier_type = ?, points_json = ?, updated_at = ?, updated_by = ?
                WHERE id = ? AND event_id = ?
                """,
                (name, barrier_type, points_json, timestamp, payload.updated_by, barrier_id, event_id),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM access_barriers WHERE id = ? AND event_id = ?",
                (barrier_id, event_id),
            ).fetchone()
        return barrier_row_to_dict(row)

    @router.delete("/events/{event_id}/access-barriers/{barrier_id}")
    def delete_barrier(event_id: str, barrier_id: str):
        with get_connection() as conn:
            conn.execute(
                "DELETE FROM access_barriers WHERE id = ? AND event_id = ?",
                (barrier_id, event_id),
            )
            conn.execute(
                "UPDATE wrstops_gates SET barrier_id = NULL WHERE event_id = ? AND barrier_id = ?",
                (event_id, barrier_id),
            )
            conn.commit()
        return {"deleted": True, "id": barrier_id}

    @router.get("/events/{event_id}/access-zones")
    def list_zones(event_id: str):
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM access_zones
                WHERE event_id = ?
                ORDER BY name COLLATE NOCASE ASC
                """,
                (event_id,),
            ).fetchall()
        return [zone_row_to_dict(row) for row in rows]

    @router.post("/events/{event_id}/access-zones")
    def create_zone(event_id: str, payload: AccessZoneCreate):
        zone_class = normalize_zone_class(payload.zone_class)
        zone_id = "zone_" + uuid4().hex[:12]
        timestamp = now_iso()
        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO access_zones (
                    id, event_id, name, zone_class, polygon_json, fill_color,
                    created_at, updated_at, updated_by
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    zone_id,
                    event_id,
                    payload.name.strip() or "Zone",
                    zone_class,
                    _points_to_json(payload.polygon),
                    resolve_fill_color(zone_class, payload.fill_color),
                    timestamp,
                    timestamp,
                    payload.updated_by,
                ),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM access_zones WHERE id = ? AND event_id = ?",
                (zone_id, event_id),
            ).fetchone()
        return zone_row_to_dict(row)

    @router.put("/events/{event_id}/access-zones/{zone_id}")
    def update_zone(event_id: str, zone_id: str, payload: AccessZoneUpdate):
        with get_connection() as conn:
            existing = conn.execute(
                "SELECT * FROM access_zones WHERE id = ? AND event_id = ?",
                (zone_id, event_id),
            ).fetchone()
            if existing is None:
                raise HTTPException(status_code=404, detail="Zone not found")

            name = payload.name.strip() if payload.name is not None else existing["name"]
            zone_class = (
                normalize_zone_class(payload.zone_class)
                if payload.zone_class is not None
                else existing["zone_class"]
            )
            polygon_json = (
                _points_to_json(payload.polygon)
                if payload.polygon is not None
                else existing["polygon_json"]
            )
            if payload.fill_color is not None:
                fill_color = resolve_fill_color(zone_class, payload.fill_color)
            elif payload.zone_class is not None:
                fill_color = resolve_fill_color(zone_class, None)
            else:
                fill_color = existing["fill_color"] or resolve_fill_color(zone_class, None)
            timestamp = now_iso()
            conn.execute(
                """
                UPDATE access_zones
                SET name = ?, zone_class = ?, polygon_json = ?, fill_color = ?,
                    updated_at = ?, updated_by = ?
                WHERE id = ? AND event_id = ?
                """,
                (
                    name,
                    zone_class,
                    polygon_json,
                    fill_color,
                    timestamp,
                    payload.updated_by,
                    zone_id,
                    event_id,
                ),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM access_zones WHERE id = ? AND event_id = ?",
                (zone_id, event_id),
            ).fetchone()
        return zone_row_to_dict(row)

    @router.delete("/events/{event_id}/access-zones/{zone_id}")
    def delete_zone(event_id: str, zone_id: str):
        with get_connection() as conn:
            conn.execute(
                "DELETE FROM access_zones WHERE id = ? AND event_id = ?",
                (zone_id, event_id),
            )
            conn.execute(
                """
                UPDATE wrstops_gates
                SET zone_a_id = CASE WHEN zone_a_id = ? THEN NULL ELSE zone_a_id END,
                    zone_b_id = CASE WHEN zone_b_id = ? THEN NULL ELSE zone_b_id END
                WHERE event_id = ?
                """,
                (zone_id, zone_id, event_id),
            )
            conn.commit()
        return {"deleted": True, "id": zone_id}

    @router.put("/events/{event_id}/wrstops-gates/{gate_id}/portal-access")
    def update_gate_portal_access(event_id: str, gate_id: str, payload: GatePortalAccessUpdate):
        with get_connection() as conn:
            existing = conn.execute(
                "SELECT * FROM wrstops_gates WHERE id = ? AND event_id = ?",
                (gate_id, event_id),
            ).fetchone()
            if existing is None:
                raise HTTPException(status_code=404, detail="WRSTOPS gate not found")

            for zone_id in [payload.zone_a_id, payload.zone_b_id]:
                if not zone_id:
                    continue
                zone = conn.execute(
                    "SELECT id FROM access_zones WHERE id = ? AND event_id = ?",
                    (zone_id, event_id),
                ).fetchone()
                if zone is None:
                    raise HTTPException(status_code=400, detail=f"Unknown zone: {zone_id}")

            if payload.barrier_id:
                barrier = conn.execute(
                    "SELECT id FROM access_barriers WHERE id = ? AND event_id = ?",
                    (payload.barrier_id, event_id),
                ).fetchone()
                if barrier is None:
                    raise HTTPException(status_code=400, detail="Unknown barrier")

            allowed = [normalize_zone_class(c) for c in payload.allowed_classes if c]
            allowed = [c for c in allowed if c in ZONE_CLASSES]

            timestamp = now_iso()
            conn.execute(
                """
                UPDATE wrstops_gates
                SET zone_a_id = ?, zone_b_id = ?, allowed_classes = ?, direction = ?,
                    barrier_id = ?, updated_at = ?, updated_by = ?
                WHERE id = ? AND event_id = ?
                """,
                (
                    payload.zone_a_id,
                    payload.zone_b_id,
                    json.dumps(allowed),
                    normalize_direction(payload.direction),
                    payload.barrier_id,
                    timestamp,
                    payload.updated_by,
                    gate_id,
                    event_id,
                ),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM wrstops_gates WHERE id = ? AND event_id = ?",
                (gate_id, event_id),
            ).fetchone()

        payload_dict = {
            "id": row["id"],
            "event_id": row["event_id"],
            "name": row["name"],
            "device_type": row["device_type"],
            "deviceType": row["device_type"],
            "map_x": row["map_x"],
            "map_y": row["map_y"],
            "mapX": row["map_x"],
            "mapY": row["map_y"],
            "latitude": row["latitude"],
            "longitude": row["longitude"],
            "accuracy_meters": row["accuracy_meters"],
            "scan_count": row["scan_count"],
            "connection_status": row["connection_status"],
            "ip_address": row["ip_address"],
            "override_status": row["override_status"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "updated_by": row["updated_by"],
        }
        payload_dict.update(enrich_wrstops_gate_dict(row))
        return payload_dict

    app.include_router(router)
