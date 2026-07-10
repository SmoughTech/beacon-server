"""Camera feed configuration + live counting state for the Beacon /count panel.

This module owns the *operator configuration* for live crowd counting that the
/count panel edits, plus the live operational state it displays. It sits on top
of the raw ingestion layer in ``camera_counting.py`` (which stores generic
``gate`` / ``density`` samples and reconciles them).

Three things are configured per feed:

* ``camera_feeds``   - a source of pixels: a browser webcam, a screen share, an
                       IP camera (RTSP/HTTP), or a still file. This is what the
                       operator selects in the panel.
* ``feed_regions``   - frame-space polygons the operator draws on a feed to label
                       areas ("outside", "zone 1", ...) or to exclude an area
                       from counting. Coordinates are normalized 0..1 in the feed
                       frame (NOT the site map).
* ``tripwire_lines`` - a line drawn across a feed. When a *tracked* person crosses
                       it, we log a directional crossing and the line's running
                       ``in``/``out`` ledger updates. This is the authoritative
                       occupancy count (see ``camera_counting`` gate semantics).

Two capabilities feed this state:

* On-screen density counting (CSRNet) -> ``camera_feeds.last_heads`` via the
  ``/density`` push. Answers "how many are on screen".
* Line-crossing (detector + tracker + tripwire) -> ``line_crossings`` via the
  ``/crossings`` push. Answers "how many entered / left". The current model does
  NOT do this yet; crossings can be pushed manually or by the future tracker.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, Callable, List, Optional
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, model_validator

FEED_KINDS = ("webcam", "ip", "screen", "file")
REGION_ROLES = ("zone", "outside", "exclude")

# Guard rails.
MAX_POLYGON_POINTS = 200
MAX_HEATMAP_CELLS = 40000
DEFAULT_STALE_AFTER_SECONDS = 120


# --------------------------------------------------------------------------- #
# Pydantic models
# --------------------------------------------------------------------------- #
class FramePoint(BaseModel):
    x: float = Field(ge=0.0, le=1.0)
    y: float = Field(ge=0.0, le=1.0)


class CameraFeedCreate(BaseModel):
    name: str = Field(default="Camera", min_length=1, max_length=120)
    kind: str = Field(default="webcam", max_length=20)
    url: Optional[str] = Field(default=None, max_length=500)
    device_id: Optional[str] = Field(default=None, max_length=200)
    location_note: Optional[str] = Field(default=None, max_length=300)
    enabled: bool = True
    updated_by: Optional[str] = "count_panel"

    @model_validator(mode="after")
    def check(self) -> "CameraFeedCreate":
        if normalize_feed_kind(self.kind) not in FEED_KINDS:
            raise ValueError("kind must be one of: webcam, ip, screen, file")
        if normalize_feed_kind(self.kind) == "ip" and not (self.url or "").strip():
            raise ValueError("ip feed requires a url (rtsp:// or http(s):// snapshot/MJPEG)")
        return self


class CameraFeedUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    kind: Optional[str] = Field(default=None, max_length=20)
    url: Optional[str] = Field(default=None, max_length=500)
    device_id: Optional[str] = Field(default=None, max_length=200)
    location_note: Optional[str] = Field(default=None, max_length=300)
    enabled: Optional[bool] = None
    updated_by: Optional[str] = "count_panel"


class FeedRegionCreate(BaseModel):
    name: str = Field(default="Zone", min_length=1, max_length=120)
    role: str = Field(default="zone", max_length=20)
    polygon: List[FramePoint] = Field(min_length=3)
    color: Optional[str] = Field(default=None, max_length=40)
    updated_by: Optional[str] = "count_panel"

    @model_validator(mode="after")
    def check(self) -> "FeedRegionCreate":
        if self.role.strip().lower() not in REGION_ROLES:
            raise ValueError("role must be one of: zone, outside, exclude")
        if len(self.polygon) > MAX_POLYGON_POINTS:
            raise ValueError(f"polygon has too many points (max {MAX_POLYGON_POINTS})")
        return self


class FeedRegionUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    role: Optional[str] = Field(default=None, max_length=20)
    polygon: Optional[List[FramePoint]] = Field(default=None, min_length=3)
    color: Optional[str] = Field(default=None, max_length=40)
    updated_by: Optional[str] = "count_panel"


class TripwireLineCreate(BaseModel):
    name: str = Field(default="Threshold", min_length=1, max_length=120)
    ax: float = Field(ge=0.0, le=1.0)
    ay: float = Field(ge=0.0, le=1.0)
    bx: float = Field(ge=0.0, le=1.0)
    by: float = Field(ge=0.0, le=1.0)
    # Which side of the A->B line counts as "in". A crossing from the other side
    # to this side is an entry (+in); the reverse is an exit (+out).
    flip: bool = False
    updated_by: Optional[str] = "count_panel"

    @model_validator(mode="after")
    def check(self) -> "TripwireLineCreate":
        if abs(self.ax - self.bx) < 1e-6 and abs(self.ay - self.by) < 1e-6:
            raise ValueError("line endpoints A and B must differ")
        return self


class TripwireLineUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    ax: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    ay: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    bx: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    by: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    flip: Optional[bool] = None
    updated_by: Optional[str] = "count_panel"


class CrossingCreate(BaseModel):
    """One directional line crossing, pushed by the tracker (or manually)."""

    direction: str = Field(max_length=4)
    track_id: Optional[str] = Field(default=None, max_length=80)
    captured_at: Optional[str] = Field(default=None, max_length=40)

    @model_validator(mode="after")
    def check(self) -> "CrossingCreate":
        if self.direction.strip().lower() not in ("in", "out"):
            raise ValueError("direction must be 'in' or 'out'")
        return self


class HeatCell(BaseModel):
    x: float = Field(ge=0.0, le=1.0)
    y: float = Field(ge=0.0, le=1.0)
    w: float = Field(ge=0.0)


class DensityPush(BaseModel):
    """A live density result for a feed, in feed-frame coordinates."""

    heads: int = Field(ge=0)
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    cells: List[HeatCell] = Field(default_factory=list)
    captured_at: Optional[str] = Field(default=None, max_length=40)

    @model_validator(mode="after")
    def check(self) -> "DensityPush":
        if len(self.cells) > MAX_HEATMAP_CELLS:
            raise ValueError(f"too many heatmap cells (max {MAX_HEATMAP_CELLS})")
        return self


# --------------------------------------------------------------------------- #
# Normalizers / row mappers
# --------------------------------------------------------------------------- #
def normalize_feed_kind(value: Optional[str]) -> str:
    raw = (value or "webcam").strip().lower()
    return raw if raw in FEED_KINDS else "webcam"


def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _age_seconds(last_seen: Optional[str], now: datetime) -> Optional[float]:
    dt = _parse_iso(last_seen)
    if dt is None:
        return None
    return max(0.0, (now - dt).total_seconds())


def feed_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "event_id": row["event_id"],
        "name": row["name"],
        "kind": row["kind"],
        "url": row["url"],
        "device_id": row["device_id"],
        "location_note": row["location_note"],
        "enabled": bool(row["enabled"]),
        "last_heads": row["last_heads"],
        "last_confidence": row["last_confidence"],
        "last_seen": row["last_seen"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "updated_by": row["updated_by"],
    }


def region_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "event_id": row["event_id"],
        "feed_id": row["feed_id"],
        "name": row["name"],
        "role": row["role"],
        "polygon": json.loads(row["polygon_json"]),
        "color": row["color"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def line_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    cin = int(row["cumulative_in"] or 0)
    cout = int(row["cumulative_out"] or 0)
    return {
        "id": row["id"],
        "event_id": row["event_id"],
        "feed_id": row["feed_id"],
        "name": row["name"],
        "ax": row["ax"],
        "ay": row["ay"],
        "bx": row["bx"],
        "by": row["by"],
        "flip": bool(row["flip"]),
        "cumulative_in": cin,
        "cumulative_out": cout,
        "net_occupancy": cin - cout,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


# --------------------------------------------------------------------------- #
# Schema
# --------------------------------------------------------------------------- #
def init_camera_feeds_db(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS camera_feeds (
            id TEXT PRIMARY KEY,
            event_id TEXT NOT NULL,
            name TEXT NOT NULL,
            kind TEXT NOT NULL DEFAULT 'webcam',
            url TEXT,
            device_id TEXT,
            location_note TEXT,
            enabled INTEGER NOT NULL DEFAULT 1,
            last_heads INTEGER,
            last_confidence REAL,
            last_seen TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            updated_by TEXT
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_camera_feeds_event ON camera_feeds(event_id)"
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS feed_regions (
            id TEXT PRIMARY KEY,
            event_id TEXT NOT NULL,
            feed_id TEXT NOT NULL,
            name TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'zone',
            polygon_json TEXT NOT NULL,
            color TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            updated_by TEXT
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_feed_regions_feed ON feed_regions(feed_id)"
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS tripwire_lines (
            id TEXT PRIMARY KEY,
            event_id TEXT NOT NULL,
            feed_id TEXT NOT NULL,
            name TEXT NOT NULL,
            ax REAL NOT NULL,
            ay REAL NOT NULL,
            bx REAL NOT NULL,
            by REAL NOT NULL,
            flip INTEGER NOT NULL DEFAULT 0,
            cumulative_in INTEGER NOT NULL DEFAULT 0,
            cumulative_out INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            updated_by TEXT
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_tripwire_lines_feed ON tripwire_lines(feed_id)"
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS line_crossings (
            id TEXT PRIMARY KEY,
            event_id TEXT NOT NULL,
            line_id TEXT NOT NULL,
            feed_id TEXT NOT NULL,
            direction TEXT NOT NULL,
            track_id TEXT,
            captured_at TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_line_crossings_line ON line_crossings(line_id, created_at)"
    )


# --------------------------------------------------------------------------- #
# Query helpers
# --------------------------------------------------------------------------- #
def _get_feed(conn: sqlite3.Connection, event_id: str, feed_id: str) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM camera_feeds WHERE id = ? AND event_id = ?",
        (feed_id, event_id),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Camera feed not found")
    return row


def _get_line(conn: sqlite3.Connection, event_id: str, line_id: str) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM tripwire_lines WHERE id = ? AND event_id = ?",
        (line_id, event_id),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Tripwire line not found")
    return row


# --------------------------------------------------------------------------- #
# Router
# --------------------------------------------------------------------------- #
def register_camera_feeds(app, get_connection: Callable, now_iso: Callable[[], str]) -> None:
    router = APIRouter()

    # ----- feeds ----------------------------------------------------------- #
    @router.get("/events/{event_id}/camera-feeds")
    def list_feeds(event_id: str):
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM camera_feeds WHERE event_id = ? ORDER BY name COLLATE NOCASE ASC",
                (event_id,),
            ).fetchall()
        return [feed_row_to_dict(r) for r in rows]

    @router.post("/events/{event_id}/camera-feeds")
    def create_feed(event_id: str, payload: CameraFeedCreate):
        feed_id = f"feed_{uuid4().hex[:12]}"
        ts = now_iso()
        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO camera_feeds (
                    id, event_id, name, kind, url, device_id, location_note,
                    enabled, created_at, updated_at, updated_by
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    feed_id,
                    event_id,
                    payload.name.strip() or "Camera",
                    normalize_feed_kind(payload.kind),
                    (payload.url or "").strip() or None,
                    (payload.device_id or "").strip() or None,
                    (payload.location_note or "").strip() or None,
                    1 if payload.enabled else 0,
                    ts,
                    ts,
                    payload.updated_by,
                ),
            )
            conn.commit()
            row = _get_feed(conn, event_id, feed_id)
        return feed_row_to_dict(row)

    @router.put("/events/{event_id}/camera-feeds/{feed_id}")
    def update_feed(event_id: str, feed_id: str, payload: CameraFeedUpdate):
        with get_connection() as conn:
            existing = _get_feed(conn, event_id, feed_id)
            name = payload.name.strip() if payload.name is not None else existing["name"]
            kind = normalize_feed_kind(payload.kind) if payload.kind is not None else existing["kind"]
            url = ((payload.url or "").strip() or None) if payload.url is not None else existing["url"]
            device_id = (
                ((payload.device_id or "").strip() or None)
                if payload.device_id is not None
                else existing["device_id"]
            )
            note = (
                ((payload.location_note or "").strip() or None)
                if payload.location_note is not None
                else existing["location_note"]
            )
            enabled = existing["enabled"] if payload.enabled is None else (1 if payload.enabled else 0)
            ts = now_iso()
            conn.execute(
                """
                UPDATE camera_feeds
                SET name = ?, kind = ?, url = ?, device_id = ?, location_note = ?,
                    enabled = ?, updated_at = ?, updated_by = ?
                WHERE id = ? AND event_id = ?
                """,
                (name, kind, url, device_id, note, enabled, ts, payload.updated_by, feed_id, event_id),
            )
            conn.commit()
            row = _get_feed(conn, event_id, feed_id)
        return feed_row_to_dict(row)

    @router.delete("/events/{event_id}/camera-feeds/{feed_id}")
    def delete_feed(event_id: str, feed_id: str):
        with get_connection() as conn:
            _get_feed(conn, event_id, feed_id)
            conn.execute("DELETE FROM camera_feeds WHERE id = ? AND event_id = ?", (feed_id, event_id))
            conn.execute("DELETE FROM feed_regions WHERE feed_id = ? AND event_id = ?", (feed_id, event_id))
            conn.execute("DELETE FROM tripwire_lines WHERE feed_id = ? AND event_id = ?", (feed_id, event_id))
            conn.execute("DELETE FROM line_crossings WHERE feed_id = ? AND event_id = ?", (feed_id, event_id))
            conn.commit()
        return {"deleted": True, "id": feed_id}

    @router.put("/events/{event_id}/camera-feeds/{feed_id}/density")
    def push_density(event_id: str, feed_id: str, payload: DensityPush):
        ts = now_iso()
        with get_connection() as conn:
            _get_feed(conn, event_id, feed_id)
            conn.execute(
                """
                UPDATE camera_feeds
                SET last_heads = ?, last_confidence = ?, last_seen = ?, updated_at = ?
                WHERE id = ? AND event_id = ?
                """,
                (payload.heads, payload.confidence, ts, ts, feed_id, event_id),
            )
            conn.commit()
        return {"feed_id": feed_id, "heads": payload.heads, "cells": len(payload.cells), "created_at": ts}

    # ----- frame regions --------------------------------------------------- #
    @router.get("/events/{event_id}/camera-feeds/{feed_id}/regions")
    def list_regions(event_id: str, feed_id: str):
        with get_connection() as conn:
            _get_feed(conn, event_id, feed_id)
            rows = conn.execute(
                "SELECT * FROM feed_regions WHERE feed_id = ? AND event_id = ? ORDER BY created_at ASC",
                (feed_id, event_id),
            ).fetchall()
        return [region_row_to_dict(r) for r in rows]

    @router.post("/events/{event_id}/camera-feeds/{feed_id}/regions")
    def create_region(event_id: str, feed_id: str, payload: FeedRegionCreate):
        region_id = f"reg_{uuid4().hex[:12]}"
        ts = now_iso()
        with get_connection() as conn:
            _get_feed(conn, event_id, feed_id)
            conn.execute(
                """
                INSERT INTO feed_regions (
                    id, event_id, feed_id, name, role, polygon_json, color,
                    created_at, updated_at, updated_by
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    region_id,
                    event_id,
                    feed_id,
                    payload.name.strip() or "Zone",
                    payload.role.strip().lower(),
                    json.dumps([{"x": p.x, "y": p.y} for p in payload.polygon]),
                    payload.color,
                    ts,
                    ts,
                    payload.updated_by,
                ),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM feed_regions WHERE id = ?", (region_id,)).fetchone()
        return region_row_to_dict(row)

    @router.put("/events/{event_id}/camera-feeds/{feed_id}/regions/{region_id}")
    def update_region(event_id: str, feed_id: str, region_id: str, payload: FeedRegionUpdate):
        with get_connection() as conn:
            existing = conn.execute(
                "SELECT * FROM feed_regions WHERE id = ? AND feed_id = ? AND event_id = ?",
                (region_id, feed_id, event_id),
            ).fetchone()
            if existing is None:
                raise HTTPException(status_code=404, detail="Region not found")
            name = payload.name.strip() if payload.name is not None else existing["name"]
            role = payload.role.strip().lower() if payload.role is not None else existing["role"]
            if role not in REGION_ROLES:
                raise HTTPException(status_code=400, detail="role must be zone, outside, or exclude")
            polygon_json = (
                json.dumps([{"x": p.x, "y": p.y} for p in payload.polygon])
                if payload.polygon is not None
                else existing["polygon_json"]
            )
            color = payload.color if payload.color is not None else existing["color"]
            ts = now_iso()
            conn.execute(
                """
                UPDATE feed_regions
                SET name = ?, role = ?, polygon_json = ?, color = ?, updated_at = ?, updated_by = ?
                WHERE id = ? AND feed_id = ? AND event_id = ?
                """,
                (name, role, polygon_json, color, ts, payload.updated_by, region_id, feed_id, event_id),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM feed_regions WHERE id = ?", (region_id,)).fetchone()
        return region_row_to_dict(row)

    @router.delete("/events/{event_id}/camera-feeds/{feed_id}/regions/{region_id}")
    def delete_region(event_id: str, feed_id: str, region_id: str):
        with get_connection() as conn:
            conn.execute(
                "DELETE FROM feed_regions WHERE id = ? AND feed_id = ? AND event_id = ?",
                (region_id, feed_id, event_id),
            )
            conn.commit()
        return {"deleted": True, "id": region_id}

    # ----- tripwire lines -------------------------------------------------- #
    @router.get("/events/{event_id}/camera-feeds/{feed_id}/lines")
    def list_lines(event_id: str, feed_id: str):
        with get_connection() as conn:
            _get_feed(conn, event_id, feed_id)
            rows = conn.execute(
                "SELECT * FROM tripwire_lines WHERE feed_id = ? AND event_id = ? ORDER BY created_at ASC",
                (feed_id, event_id),
            ).fetchall()
        return [line_row_to_dict(r) for r in rows]

    @router.post("/events/{event_id}/camera-feeds/{feed_id}/lines")
    def create_line(event_id: str, feed_id: str, payload: TripwireLineCreate):
        line_id = f"line_{uuid4().hex[:12]}"
        ts = now_iso()
        with get_connection() as conn:
            _get_feed(conn, event_id, feed_id)
            conn.execute(
                """
                INSERT INTO tripwire_lines (
                    id, event_id, feed_id, name, ax, ay, bx, by, flip,
                    cumulative_in, cumulative_out, created_at, updated_at, updated_by
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?, ?, ?)
                """,
                (
                    line_id,
                    event_id,
                    feed_id,
                    payload.name.strip() or "Threshold",
                    payload.ax,
                    payload.ay,
                    payload.bx,
                    payload.by,
                    1 if payload.flip else 0,
                    ts,
                    ts,
                    payload.updated_by,
                ),
            )
            conn.commit()
            row = _get_line(conn, event_id, line_id)
        return line_row_to_dict(row)

    @router.put("/events/{event_id}/camera-feeds/{feed_id}/lines/{line_id}")
    def update_line(event_id: str, feed_id: str, line_id: str, payload: TripwireLineUpdate):
        with get_connection() as conn:
            existing = conn.execute(
                "SELECT * FROM tripwire_lines WHERE id = ? AND feed_id = ? AND event_id = ?",
                (line_id, feed_id, event_id),
            ).fetchone()
            if existing is None:
                raise HTTPException(status_code=404, detail="Tripwire line not found")
            name = payload.name.strip() if payload.name is not None else existing["name"]
            ax = payload.ax if payload.ax is not None else existing["ax"]
            ay = payload.ay if payload.ay is not None else existing["ay"]
            bx = payload.bx if payload.bx is not None else existing["bx"]
            by = payload.by if payload.by is not None else existing["by"]
            flip = existing["flip"] if payload.flip is None else (1 if payload.flip else 0)
            ts = now_iso()
            conn.execute(
                """
                UPDATE tripwire_lines
                SET name = ?, ax = ?, ay = ?, bx = ?, by = ?, flip = ?, updated_at = ?, updated_by = ?
                WHERE id = ? AND feed_id = ? AND event_id = ?
                """,
                (name, ax, ay, bx, by, flip, ts, payload.updated_by, line_id, feed_id, event_id),
            )
            conn.commit()
            row = _get_line(conn, event_id, line_id)
        return line_row_to_dict(row)

    @router.delete("/events/{event_id}/camera-feeds/{feed_id}/lines/{line_id}")
    def delete_line(event_id: str, feed_id: str, line_id: str):
        with get_connection() as conn:
            conn.execute(
                "DELETE FROM tripwire_lines WHERE id = ? AND feed_id = ? AND event_id = ?",
                (line_id, feed_id, event_id),
            )
            conn.execute("DELETE FROM line_crossings WHERE line_id = ? AND event_id = ?", (line_id, event_id))
            conn.commit()
        return {"deleted": True, "id": line_id}

    @router.post("/events/{event_id}/camera-feeds/{feed_id}/lines/{line_id}/crossings")
    def push_crossing(event_id: str, feed_id: str, line_id: str, payload: CrossingCreate):
        direction = payload.direction.strip().lower()
        ts = now_iso()
        crossing_id = f"cross_{uuid4().hex[:12]}"
        with get_connection() as conn:
            _get_line(conn, event_id, line_id)
            conn.execute(
                """
                INSERT INTO line_crossings (
                    id, event_id, line_id, feed_id, direction, track_id, captured_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (crossing_id, event_id, line_id, feed_id, direction, payload.track_id, payload.captured_at, ts),
            )
            if direction == "in":
                conn.execute(
                    "UPDATE tripwire_lines SET cumulative_in = cumulative_in + 1, updated_at = ? WHERE id = ?",
                    (ts, line_id),
                )
            else:
                conn.execute(
                    "UPDATE tripwire_lines SET cumulative_out = cumulative_out + 1, updated_at = ? WHERE id = ?",
                    (ts, line_id),
                )
            conn.commit()
            row = _get_line(conn, event_id, line_id)
        return {"crossing_id": crossing_id, "direction": direction, "line": line_row_to_dict(row)}

    @router.post("/events/{event_id}/camera-feeds/{feed_id}/lines/{line_id}/reset")
    def reset_line(event_id: str, feed_id: str, line_id: str):
        ts = now_iso()
        with get_connection() as conn:
            _get_line(conn, event_id, line_id)
            conn.execute(
                "UPDATE tripwire_lines SET cumulative_in = 0, cumulative_out = 0, updated_at = ? WHERE id = ?",
                (ts, line_id),
            )
            conn.execute("DELETE FROM line_crossings WHERE line_id = ? AND event_id = ?", (line_id, event_id))
            conn.commit()
            row = _get_line(conn, event_id, line_id)
        return line_row_to_dict(row)

    # ----- consolidated live state ---------------------------------------- #
    @router.get("/events/{event_id}/camera-state")
    def camera_state(
        event_id: str,
        stale_after_seconds: int = Query(default=DEFAULT_STALE_AFTER_SECONDS, ge=5, le=86400),
    ):
        now = datetime.now(timezone.utc)
        with get_connection() as conn:
            feeds = conn.execute(
                "SELECT * FROM camera_feeds WHERE event_id = ?", (event_id,)
            ).fetchall()
            regions = conn.execute(
                "SELECT * FROM feed_regions WHERE event_id = ?", (event_id,)
            ).fetchall()
            lines = conn.execute(
                "SELECT * FROM tripwire_lines WHERE event_id = ?", (event_id,)
            ).fetchall()

        regions_by_feed: dict[str, list] = {}
        for r in regions:
            regions_by_feed.setdefault(r["feed_id"], []).append(region_row_to_dict(r))
        lines_by_feed: dict[str, list] = {}
        for ln in lines:
            lines_by_feed.setdefault(ln["feed_id"], []).append(line_row_to_dict(ln))

        feed_views = []
        density_total = 0
        has_density = False
        for f in feeds:
            age = _age_seconds(f["last_seen"], now)
            stale = age is None or age > stale_after_seconds
            view = feed_row_to_dict(f)
            view["age_seconds"] = round(age, 1) if age is not None else None
            view["stale"] = stale
            view["regions"] = regions_by_feed.get(f["id"], [])
            view["lines"] = lines_by_feed.get(f["id"], [])
            if not stale and f["last_heads"] is not None:
                density_total += int(f["last_heads"])
                has_density = True
            feed_views.append(view)

        total_in = sum(int(ln["cumulative_in"] or 0) for ln in lines)
        total_out = sum(int(ln["cumulative_out"] or 0) for ln in lines)

        return {
            "event_id": event_id,
            "generated_at": now.isoformat(),
            "stale_after_seconds": stale_after_seconds,
            "feeds": feed_views,
            "occupancy_ledger": total_in - total_out,
            "total_in": total_in,
            "total_out": total_out,
            "density_observed": density_total if has_density else None,
            "has_density": has_density,
        }

    app.include_router(router)
