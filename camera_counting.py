"""Camera-based crowd counting aggregation layer for Beacon.

Beacon does not run any computer vision itself. External counters (gate
line-crossing trackers and crowd-density models) run elsewhere and PUSH their
results here. This module stores those results and reconciles them into a single
defensible occupancy figure for display on the event map.

Two kinds of counting source:

* ``gate``    - a line-crossing counter at an entrance/exit. Reports cumulative
                ``in`` and ``out`` tallies. ``in - out`` across all gates is the
                authoritative (auditable) occupancy ledger.
* ``density`` - a crowd-density model watching an area. Reports an instantaneous
                head count (``heads``) and may also push a heatmap (already in
                map-normalized coordinates). Used as a live cross-check of the
                ledger and to show *where* the crowd is.

The two figures are NOT summed: they are two independent estimates of the same
population. Their agreement is the defensibility signal; their divergence is an
operational alert.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, Callable, List, Optional
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field, model_validator

SOURCE_KINDS = ("gate", "density")

# A source is considered stale (offline) if its latest sample is older than this.
DEFAULT_STALE_AFTER_SECONDS = 120

# Guard against absurd heatmap payloads.
MAX_HEATMAP_CELLS = 40000


# --------------------------------------------------------------------------- #
# Pydantic models
# --------------------------------------------------------------------------- #
class CountSourceCreate(BaseModel):
    name: str = Field(default="Camera", min_length=1, max_length=120)
    kind: str = Field(default="density", max_length=20)
    zone_id: Optional[str] = Field(default=None, max_length=80)
    notes: Optional[str] = Field(default=None, max_length=500)
    updated_by: Optional[str] = "dash_counts"

    @model_validator(mode="after")
    def check_kind(self) -> "CountSourceCreate":
        if normalize_kind(self.kind) not in SOURCE_KINDS:
            raise ValueError("kind must be 'gate' or 'density'")
        return self


class CountSourceUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    zone_id: Optional[str] = Field(default=None, max_length=80)
    status: Optional[str] = Field(default=None, max_length=20)
    notes: Optional[str] = Field(default=None, max_length=500)
    updated_by: Optional[str] = "dash_counts"


class CountSampleCreate(BaseModel):
    """One measurement pushed by an external counter.

    Gate sources send ``cumulative_in`` / ``cumulative_out``. Density sources send
    ``heads`` (and optionally ``confidence``). ``captured_at`` is the time the
    measurement was actually taken by the counter, if known.
    """

    cumulative_in: Optional[int] = Field(default=None, ge=0)
    cumulative_out: Optional[int] = Field(default=None, ge=0)
    heads: Optional[int] = Field(default=None, ge=0)
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    captured_at: Optional[str] = Field(default=None, max_length=40)


class HeatmapCell(BaseModel):
    x: float = Field(ge=0.0, le=1.0)
    y: float = Field(ge=0.0, le=1.0)
    w: float = Field(ge=0.0)


class HeatmapUpsert(BaseModel):
    """A density heatmap frame, already projected into map coordinates (0..1)."""

    cells: List[HeatmapCell] = Field(default_factory=list)
    captured_at: Optional[str] = Field(default=None, max_length=40)

    @model_validator(mode="after")
    def check_cells(self) -> "HeatmapUpsert":
        if len(self.cells) > MAX_HEATMAP_CELLS:
            raise ValueError(f"heatmap has too many cells (max {MAX_HEATMAP_CELLS})")
        return self


# --------------------------------------------------------------------------- #
# Normalizers / row mappers
# --------------------------------------------------------------------------- #
def normalize_kind(value: Optional[str]) -> str:
    raw = (value or "density").strip().lower()
    return raw if raw in SOURCE_KINDS else "density"


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


def source_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "event_id": row["event_id"],
        "name": row["name"],
        "kind": row["kind"],
        "zone_id": row["zone_id"],
        "status": row["status"],
        "notes": row["notes"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "updated_by": row["updated_by"],
    }


def sample_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "event_id": row["event_id"],
        "source_id": row["source_id"],
        "kind": row["kind"],
        "cumulative_in": row["cumulative_in"],
        "cumulative_out": row["cumulative_out"],
        "heads": row["heads"],
        "confidence": row["confidence"],
        "captured_at": row["captured_at"],
        "created_at": row["created_at"],
    }


# --------------------------------------------------------------------------- #
# Reconciliation (pure, unit-testable)
# --------------------------------------------------------------------------- #
def reconcile_counts(
    gate_latest: List[dict[str, Any]],
    density_latest: List[dict[str, Any]],
) -> dict[str, Any]:
    """Combine the latest per-source values into a single summary.

    ``gate_latest`` items: {source_id, name, zone_id, cumulative_in, cumulative_out, ...}
    ``density_latest`` items: {source_id, name, zone_id, heads, ...}

    The gate ledger is authoritative for the headline total. Density is a
    cross-check and is only summed as a caveated estimate (overlapping camera
    coverage would double-count, so the site total is best read per-zone).
    """
    total_in = sum(int(g.get("cumulative_in") or 0) for g in gate_latest)
    total_out = sum(int(g.get("cumulative_out") or 0) for g in gate_latest)
    occupancy_ledger = total_in - total_out

    density_observed = sum(int(d.get("heads") or 0) for d in density_latest)
    has_density = len(density_latest) > 0

    divergence_abs: Optional[int] = None
    divergence_pct: Optional[float] = None
    if has_density:
        divergence_abs = density_observed - occupancy_ledger
        if occupancy_ledger > 0:
            divergence_pct = round(100.0 * divergence_abs / occupancy_ledger, 1)

    # Per-zone density rollup (None zone grouped under "unzoned").
    zone_totals: dict[str, int] = {}
    for d in density_latest:
        zone_key = d.get("zone_id") or "__unzoned__"
        zone_totals[zone_key] = zone_totals.get(zone_key, 0) + int(d.get("heads") or 0)
    per_zone = [
        {"zone_id": None if k == "__unzoned__" else k, "density_heads": v}
        for k, v in sorted(zone_totals.items(), key=lambda kv: kv[0])
    ]

    return {
        "headline_total": occupancy_ledger,
        "occupancy_ledger": occupancy_ledger,
        "total_in": total_in,
        "total_out": total_out,
        "density_observed": density_observed if has_density else None,
        "has_density": has_density,
        "divergence": {
            "absolute": divergence_abs,
            "pct": divergence_pct,
        },
        "per_zone": per_zone,
        "gate_source_count": len(gate_latest),
        "density_source_count": len(density_latest),
    }


# --------------------------------------------------------------------------- #
# Schema
# --------------------------------------------------------------------------- #
def init_camera_counting_db(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS count_sources (
            id TEXT PRIMARY KEY,
            event_id TEXT NOT NULL,
            name TEXT NOT NULL,
            kind TEXT NOT NULL DEFAULT 'density',
            zone_id TEXT,
            status TEXT NOT NULL DEFAULT 'active',
            notes TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            updated_by TEXT
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_count_sources_event_id ON count_sources(event_id)"
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS count_samples (
            id TEXT PRIMARY KEY,
            event_id TEXT NOT NULL,
            source_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            cumulative_in INTEGER,
            cumulative_out INTEGER,
            heads INTEGER,
            confidence REAL,
            captured_at TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_count_samples_source ON count_samples(source_id, created_at)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_count_samples_event ON count_samples(event_id, created_at)"
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS count_heatmaps (
            source_id TEXT PRIMARY KEY,
            event_id TEXT NOT NULL,
            cells_json TEXT NOT NULL,
            cell_count INTEGER NOT NULL DEFAULT 0,
            max_weight REAL NOT NULL DEFAULT 0,
            captured_at TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_count_heatmaps_event ON count_heatmaps(event_id)"
    )


# --------------------------------------------------------------------------- #
# Query helpers
# --------------------------------------------------------------------------- #
def _get_source(conn: sqlite3.Connection, event_id: str, source_id: str) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM count_sources WHERE id = ? AND event_id = ?",
        (source_id, event_id),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Count source not found")
    return row


def _latest_samples_by_source(conn: sqlite3.Connection, event_id: str) -> dict[str, sqlite3.Row]:
    """Latest sample per source for the event (one row per source)."""
    rows = conn.execute(
        """
        SELECT s.*
        FROM count_samples s
        JOIN (
            SELECT source_id, MAX(created_at) AS max_created
            FROM count_samples
            WHERE event_id = ?
            GROUP BY source_id
        ) latest
          ON s.source_id = latest.source_id AND s.created_at = latest.max_created
        WHERE s.event_id = ?
        """,
        (event_id, event_id),
    ).fetchall()
    # In the unlikely event of identical timestamps, keep the last seen.
    return {row["source_id"]: row for row in rows}


# --------------------------------------------------------------------------- #
# Router
# --------------------------------------------------------------------------- #
def register_camera_counting(app, get_connection: Callable, now_iso: Callable[[], str]) -> None:
    router = APIRouter()

    # ----- source registry ------------------------------------------------- #
    @router.get("/events/{event_id}/count-sources")
    def list_sources(event_id: str):
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM count_sources
                WHERE event_id = ?
                ORDER BY kind ASC, name COLLATE NOCASE ASC
                """,
                (event_id,),
            ).fetchall()
        return [source_row_to_dict(r) for r in rows]

    @router.post("/events/{event_id}/count-sources")
    def create_source(event_id: str, payload: CountSourceCreate):
        kind = normalize_kind(payload.kind)
        source_id = f"csrc_{uuid4().hex[:12]}"
        timestamp = now_iso()
        with get_connection() as conn:
            if payload.zone_id:
                zone = conn.execute(
                    "SELECT id FROM access_zones WHERE id = ? AND event_id = ?",
                    (payload.zone_id, event_id),
                ).fetchone()
                if zone is None:
                    raise HTTPException(status_code=400, detail=f"Unknown zone: {payload.zone_id}")
            conn.execute(
                """
                INSERT INTO count_sources (
                    id, event_id, name, kind, zone_id, status, notes,
                    created_at, updated_at, updated_by
                ) VALUES (?, ?, ?, ?, ?, 'active', ?, ?, ?, ?)
                """,
                (
                    source_id,
                    event_id,
                    payload.name.strip() or "Camera",
                    kind,
                    payload.zone_id,
                    payload.notes,
                    timestamp,
                    timestamp,
                    payload.updated_by,
                ),
            )
            conn.commit()
            row = _get_source(conn, event_id, source_id)
        return source_row_to_dict(row)

    @router.get("/events/{event_id}/count-sources/{source_id}")
    def get_source(event_id: str, source_id: str):
        with get_connection() as conn:
            row = _get_source(conn, event_id, source_id)
        return source_row_to_dict(row)

    @router.put("/events/{event_id}/count-sources/{source_id}")
    def update_source(event_id: str, source_id: str, payload: CountSourceUpdate):
        with get_connection() as conn:
            existing = _get_source(conn, event_id, source_id)
            if payload.zone_id:
                zone = conn.execute(
                    "SELECT id FROM access_zones WHERE id = ? AND event_id = ?",
                    (payload.zone_id, event_id),
                ).fetchone()
                if zone is None:
                    raise HTTPException(status_code=400, detail=f"Unknown zone: {payload.zone_id}")

            name = payload.name.strip() if payload.name is not None else existing["name"]
            zone_id = payload.zone_id if payload.zone_id is not None else existing["zone_id"]
            status = (payload.status or existing["status"]).strip().lower()
            notes = payload.notes if payload.notes is not None else existing["notes"]
            timestamp = now_iso()
            conn.execute(
                """
                UPDATE count_sources
                SET name = ?, zone_id = ?, status = ?, notes = ?, updated_at = ?, updated_by = ?
                WHERE id = ? AND event_id = ?
                """,
                (name, zone_id, status, notes, timestamp, payload.updated_by, source_id, event_id),
            )
            conn.commit()
            row = _get_source(conn, event_id, source_id)
        return source_row_to_dict(row)

    @router.delete("/events/{event_id}/count-sources/{source_id}")
    def delete_source(event_id: str, source_id: str):
        with get_connection() as conn:
            conn.execute(
                "DELETE FROM count_sources WHERE id = ? AND event_id = ?",
                (source_id, event_id),
            )
            conn.execute(
                "DELETE FROM count_samples WHERE source_id = ? AND event_id = ?",
                (source_id, event_id),
            )
            conn.execute(
                "DELETE FROM count_heatmaps WHERE source_id = ? AND event_id = ?",
                (source_id, event_id),
            )
            conn.commit()
        return {"deleted": True, "id": source_id}

    # ----- sample ingestion ------------------------------------------------ #
    @router.post("/events/{event_id}/count-sources/{source_id}/samples")
    def push_sample(event_id: str, source_id: str, payload: CountSampleCreate):
        with get_connection() as conn:
            source = _get_source(conn, event_id, source_id)
            kind = source["kind"]

            if kind == "gate":
                if payload.cumulative_in is None and payload.cumulative_out is None:
                    raise HTTPException(
                        status_code=400,
                        detail="gate sample requires cumulative_in and/or cumulative_out",
                    )
            elif kind == "density":
                if payload.heads is None:
                    raise HTTPException(
                        status_code=400, detail="density sample requires heads"
                    )

            sample_id = f"csmp_{uuid4().hex[:12]}"
            timestamp = now_iso()
            conn.execute(
                """
                INSERT INTO count_samples (
                    id, event_id, source_id, kind,
                    cumulative_in, cumulative_out, heads, confidence,
                    captured_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    sample_id,
                    event_id,
                    source_id,
                    kind,
                    payload.cumulative_in,
                    payload.cumulative_out,
                    payload.heads,
                    payload.confidence,
                    payload.captured_at,
                    timestamp,
                ),
            )
            # Keep the source marked active whenever it reports in.
            conn.execute(
                "UPDATE count_sources SET status = 'active', updated_at = ? WHERE id = ? AND event_id = ?",
                (timestamp, source_id, event_id),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM count_samples WHERE id = ?", (sample_id,)
            ).fetchone()
        return sample_row_to_dict(row)

    @router.get("/events/{event_id}/count-sources/{source_id}/samples")
    def list_samples(event_id: str, source_id: str, limit: int = Query(default=200, ge=1, le=5000)):
        with get_connection() as conn:
            _get_source(conn, event_id, source_id)
            rows = conn.execute(
                """
                SELECT * FROM count_samples
                WHERE event_id = ? AND source_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (event_id, source_id, limit),
            ).fetchall()
        return [sample_row_to_dict(r) for r in rows]

    # ----- heatmap (latest frame per density source) ----------------------- #
    @router.put("/events/{event_id}/count-sources/{source_id}/heatmap")
    def upsert_heatmap(event_id: str, source_id: str, payload: HeatmapUpsert):
        with get_connection() as conn:
            source = _get_source(conn, event_id, source_id)
            if source["kind"] != "density":
                raise HTTPException(status_code=400, detail="Only density sources carry heatmaps")
            cells = [{"x": c.x, "y": c.y, "w": c.w} for c in payload.cells]
            max_weight = max((c["w"] for c in cells), default=0.0)
            timestamp = now_iso()
            conn.execute(
                """
                INSERT INTO count_heatmaps (
                    source_id, event_id, cells_json, cell_count, max_weight, captured_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_id) DO UPDATE SET
                    event_id = excluded.event_id,
                    cells_json = excluded.cells_json,
                    cell_count = excluded.cell_count,
                    max_weight = excluded.max_weight,
                    captured_at = excluded.captured_at,
                    created_at = excluded.created_at
                """,
                (
                    source_id,
                    event_id,
                    json.dumps(cells),
                    len(cells),
                    max_weight,
                    payload.captured_at,
                    timestamp,
                ),
            )
            conn.commit()
        return {
            "source_id": source_id,
            "cell_count": len(cells),
            "max_weight": max_weight,
            "created_at": timestamp,
        }

    @router.get("/events/{event_id}/count-sources/{source_id}/heatmap")
    def get_heatmap(event_id: str, source_id: str):
        with get_connection() as conn:
            _get_source(conn, event_id, source_id)
            row = conn.execute(
                "SELECT * FROM count_heatmaps WHERE source_id = ? AND event_id = ?",
                (source_id, event_id),
            ).fetchone()
        if row is None:
            return {"source_id": source_id, "cells": [], "max_weight": 0.0, "created_at": None}
        return {
            "source_id": source_id,
            "cells": json.loads(row["cells_json"]),
            "max_weight": row["max_weight"],
            "captured_at": row["captured_at"],
            "created_at": row["created_at"],
        }

    @router.get("/events/{event_id}/counts/heatmap")
    def combined_heatmap(event_id: str):
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM count_heatmaps WHERE event_id = ?",
                (event_id,),
            ).fetchall()
        return {
            "event_id": event_id,
            "sources": [
                {
                    "source_id": r["source_id"],
                    "cells": json.loads(r["cells_json"]),
                    "max_weight": r["max_weight"],
                    "created_at": r["created_at"],
                }
                for r in rows
            ],
        }

    # ----- reconciled summary --------------------------------------------- #
    @router.get("/events/{event_id}/counts/summary")
    def counts_summary(
        event_id: str,
        stale_after_seconds: int = Query(default=DEFAULT_STALE_AFTER_SECONDS, ge=5, le=86400),
    ):
        now = datetime.now(timezone.utc)
        with get_connection() as conn:
            sources = conn.execute(
                "SELECT * FROM count_sources WHERE event_id = ?",
                (event_id,),
            ).fetchall()
            latest = _latest_samples_by_source(conn, event_id)

        gate_latest: list[dict[str, Any]] = []
        density_latest: list[dict[str, Any]] = []
        source_views: list[dict[str, Any]] = []

        for src in sources:
            sample = latest.get(src["id"])
            last_seen = sample["created_at"] if sample is not None else None
            age = _age_seconds(last_seen, now)
            stale = age is None or age > stale_after_seconds
            view = {
                "source_id": src["id"],
                "name": src["name"],
                "kind": src["kind"],
                "zone_id": src["zone_id"],
                "last_seen": last_seen,
                "age_seconds": round(age, 1) if age is not None else None,
                "stale": stale,
            }
            if src["kind"] == "gate":
                view["cumulative_in"] = sample["cumulative_in"] if sample else None
                view["cumulative_out"] = sample["cumulative_out"] if sample else None
                if not stale and sample is not None:
                    gate_latest.append(
                        {
                            "source_id": src["id"],
                            "name": src["name"],
                            "zone_id": src["zone_id"],
                            "cumulative_in": sample["cumulative_in"],
                            "cumulative_out": sample["cumulative_out"],
                        }
                    )
            else:
                view["heads"] = sample["heads"] if sample else None
                view["confidence"] = sample["confidence"] if sample else None
                if not stale and sample is not None:
                    density_latest.append(
                        {
                            "source_id": src["id"],
                            "name": src["name"],
                            "zone_id": src["zone_id"],
                            "heads": sample["heads"],
                        }
                    )
            source_views.append(view)

        summary = reconcile_counts(gate_latest, density_latest)
        summary["event_id"] = event_id
        summary["generated_at"] = now.isoformat()
        summary["stale_after_seconds"] = stale_after_seconds
        summary["sources"] = source_views
        return summary

    # ----- occupancy time series ------------------------------------------ #
    @router.get("/events/{event_id}/counts/timeseries")
    def occupancy_timeseries(event_id: str, limit: int = Query(default=500, ge=1, le=10000)):
        """Occupancy over time from gate samples, joined across all gate sources.

        For each gate sample timestamp we carry forward the last known value of
        every other gate source, so occupancy = sum(in) - sum(out) at that moment.
        """
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT created_at, source_id, cumulative_in, cumulative_out
                FROM count_samples
                WHERE event_id = ? AND kind = 'gate'
                ORDER BY created_at ASC
                """,
                (event_id,),
            ).fetchall()

        state: dict[str, tuple[int, int]] = {}
        series: list[dict[str, Any]] = []
        for r in rows:
            state[r["source_id"]] = (
                int(r["cumulative_in"] or 0),
                int(r["cumulative_out"] or 0),
            )
            total_in = sum(v[0] for v in state.values())
            total_out = sum(v[1] for v in state.values())
            series.append(
                {
                    "t": r["created_at"],
                    "occupancy": total_in - total_out,
                    "total_in": total_in,
                    "total_out": total_out,
                }
            )

        if len(series) > limit:
            series = series[-limit:]
        return {"event_id": event_id, "points": series}

    # ----- self-contained live dashboard ---------------------------------- #
    @router.get("/events/{event_id}/counts/live", response_class=HTMLResponse)
    def counts_live_page(event_id: str):
        return HTMLResponse(_LIVE_PAGE_HTML.replace("__EVENT_ID__", event_id))

    app.include_router(router)


# --------------------------------------------------------------------------- #
# Live dashboard page (vanilla JS, polls the JSON endpoints above)
# --------------------------------------------------------------------------- #
_LIVE_PAGE_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Beacon - Live Crowd Counts</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body { margin: 0; font-family: -apple-system, Segoe UI, Roboto, sans-serif;
         background: #0d1117; color: #e6edf3; }
  header { padding: 14px 20px; border-bottom: 1px solid #21262d; display: flex;
           align-items: baseline; gap: 12px; }
  header h1 { font-size: 16px; margin: 0; font-weight: 600; }
  header .evt { color: #7d8590; font-size: 13px; }
  .wrap { display: grid; grid-template-columns: 340px 1fr; gap: 16px; padding: 16px; }
  .cards { display: grid; gap: 12px; align-content: start; }
  .card { background: #161b22; border: 1px solid #21262d; border-radius: 10px; padding: 14px 16px; }
  .card .label { font-size: 11px; text-transform: uppercase; letter-spacing: .06em; color: #7d8590; }
  .card .big { font-size: 40px; font-weight: 700; margin-top: 4px; line-height: 1; }
  .row { display: flex; justify-content: space-between; font-size: 13px; margin-top: 6px; color: #adbac7; }
  .badge { display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 11px; font-weight: 600; }
  .ok { background: rgba(63,185,80,.18); color: #57d364; }
  .warn { background: rgba(210,153,34,.20); color: #e3b341; }
  .bad { background: rgba(248,81,73,.18); color: #ff7b72; }
  .mapwrap { position: relative; background: #161b22; border: 1px solid #21262d;
             border-radius: 10px; overflow: hidden; min-height: 300px; }
  .mapwrap img { display: block; width: 100%; }
  .mapwrap canvas { position: absolute; inset: 0; width: 100%; height: 100%; }
  table { width: 100%; border-collapse: collapse; font-size: 12.5px; }
  th, td { text-align: left; padding: 6px 8px; border-bottom: 1px solid #21262d; }
  th { color: #7d8590; font-weight: 500; }
  .muted { color: #7d8590; }
  .dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; margin-right: 6px; }
  .dot.live { background: #57d364; } .dot.stale { background: #ff7b72; }
</style>
</head>
<body>
<header>
  <h1>Live Crowd Counts</h1>
  <span class="evt" id="evt"></span>
  <span class="evt" id="ts" style="margin-left:auto"></span>
</header>
<div class="wrap">
  <div class="cards">
    <div class="card">
      <div class="label">Occupancy (gate ledger &middot; authoritative)</div>
      <div class="big" id="occ">&mdash;</div>
      <div class="row"><span>In</span><span id="tin">&mdash;</span></div>
      <div class="row"><span>Out</span><span id="tout">&mdash;</span></div>
    </div>
    <div class="card">
      <div class="label">Density observed (cross-check)</div>
      <div class="big" id="dens">&mdash;</div>
      <div class="row"><span>vs ledger</span><span id="div">&mdash;</span></div>
    </div>
    <div class="card">
      <div class="label">Sources</div>
      <table id="srctab"><thead><tr><th>Name</th><th>Kind</th><th>Value</th><th>Seen</th></tr></thead>
      <tbody></tbody></table>
    </div>
  </div>
  <div class="mapwrap" id="mapwrap">
    <img id="map" alt="event map" />
    <canvas id="heat"></canvas>
  </div>
</div>
<script>
const EVENT_ID = "__EVENT_ID__";
document.getElementById("evt").textContent = EVENT_ID;

async function j(url){ const r = await fetch(url); if(!r.ok) throw new Error(url); return r.json(); }

function fmt(n){ return (n===null||n===undefined) ? "\u2014" : Number(n).toLocaleString(); }

async function loadMap(){
  try {
    const evt = await j(`/events/${EVENT_ID}`);
    if (evt.map_url) document.getElementById("map").src = evt.map_url;
  } catch(e){}
}

function drawHeat(sources){
  const img = document.getElementById("map");
  const cv = document.getElementById("heat");
  const w = img.clientWidth || cv.clientWidth, h = img.clientHeight || cv.clientHeight;
  if(!w || !h) return;
  cv.width = w; cv.height = h;
  const ctx = cv.getContext("2d");
  ctx.clearRect(0,0,w,h);
  for(const s of sources){
    const mx = s.max_weight || 1;
    for(const c of s.cells){
      const alpha = Math.min(0.75, (c.w/mx) * 0.75);
      const rad = Math.max(10, w*0.02);
      const g = ctx.createRadialGradient(c.x*w, c.y*h, 0, c.x*w, c.y*h, rad);
      g.addColorStop(0, `rgba(255,80,40,${alpha})`);
      g.addColorStop(1, "rgba(255,80,40,0)");
      ctx.fillStyle = g;
      ctx.fillRect(c.x*w - rad, c.y*h - rad, rad*2, rad*2);
    }
  }
}

async function tick(){
  try {
    const [sum, heat] = await Promise.all([
      j(`/events/${EVENT_ID}/counts/summary`),
      j(`/events/${EVENT_ID}/counts/heatmap`),
    ]);
    document.getElementById("occ").textContent = fmt(sum.occupancy_ledger);
    document.getElementById("tin").textContent = fmt(sum.total_in);
    document.getElementById("tout").textContent = fmt(sum.total_out);
    document.getElementById("dens").textContent = sum.has_density ? fmt(sum.density_observed) : "\u2014";
    document.getElementById("ts").textContent = "updated " + new Date().toLocaleTimeString();

    const dv = document.getElementById("div");
    if(sum.has_density && sum.divergence.absolute!==null){
      const a = sum.divergence.absolute, p = sum.divergence.pct;
      const cls = (p===null) ? "warn" : (Math.abs(p) <= 10 ? "ok" : (Math.abs(p) <= 25 ? "warn" : "bad"));
      dv.innerHTML = `<span class="badge ${cls}">${a>0?"+":""}${fmt(a)}${p===null?"":" ("+p+"%)"}</span>`;
    } else { dv.textContent = "\u2014"; }

    const tb = document.querySelector("#srctab tbody");
    tb.innerHTML = "";
    for(const s of sum.sources){
      const val = s.kind==="gate"
        ? `${fmt(s.cumulative_in)} in / ${fmt(s.cumulative_out)} out`
        : fmt(s.heads);
      const dot = s.stale ? '<span class="dot stale"></span>' : '<span class="dot live"></span>';
      const seen = s.age_seconds===null ? "never" : Math.round(s.age_seconds)+"s ago";
      tb.insertAdjacentHTML("beforeend",
        `<tr><td>${dot}${s.name}</td><td class="muted">${s.kind}</td><td>${val}</td><td class="muted">${seen}</td></tr>`);
    }
    drawHeat(heat.sources || []);
  } catch(e){ /* keep last good view */ }
}

loadMap();
tick();
setInterval(tick, 3000);
window.addEventListener("resize", () => tick());
</script>
</body>
</html>
"""
