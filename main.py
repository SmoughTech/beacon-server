from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional, List
import sqlite3
import os
import math
from datetime import datetime, timezone
from uuid import uuid4


DATABASE_PATH = os.getenv("DATABASE_PATH", "beacon.db")

app = FastAPI(title="Beacon Server", version="3.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


BUILT_IN_POIS = [
    {"id": "medical", "name": "Medical", "category": "Services & Amenities", "map_x": 0.57, "map_y": 0.64},
    {"id": "restrooms", "name": "Restrooms", "category": "Services & Amenities", "map_x": 0.51, "map_y": 0.62},
    {"id": "water", "name": "Water Stations", "category": "Services & Amenities", "map_x": 0.46, "map_y": 0.56},
    {"id": "guest_services", "name": "Guest Services", "category": "Services & Amenities", "map_x": 0.63, "map_y": 0.73},
    {"id": "info_lost_found", "name": "Info + Lost & Found", "category": "Services & Amenities", "map_x": 0.55, "map_y": 0.58},

    {"id": "lightning", "name": "Lightning", "category": "Stages", "map_x": 0.36, "map_y": 0.42},
    {"id": "thunder", "name": "Thunder", "category": "Stages", "map_x": 0.55, "map_y": 0.42},
    {"id": "junkyard", "name": "Junkyard", "category": "Stages", "map_x": 0.43, "map_y": 0.36},
    {"id": "woogie", "name": "Woogie", "category": "Stages", "map_x": 0.57, "map_y": 0.76},
    {"id": "stacks", "name": "Stacks", "category": "Stages", "map_x": 0.48, "map_y": 0.74},
    {"id": "grand_artique", "name": "Grand Artique", "category": "Stages", "map_x": 0.42, "map_y": 0.66},
    {"id": "lighthouse", "name": "Lighthouse & Moon Room", "category": "Stages", "map_x": 0.48, "map_y": 0.68},

    {"id": "sunset_plaza", "name": "Sunset Plaza", "category": "Plazas", "map_x": 0.18, "map_y": 0.38},
    {"id": "high_noon_plaza", "name": "High Noon Plaza", "category": "Plazas", "map_x": 0.51, "map_y": 0.20},
    {"id": "sunrise_plaza", "name": "Sunrise Plaza", "category": "Plazas", "map_x": 0.80, "map_y": 0.44},

    {"id": "atlaswyld_entrance", "name": "Atlaswyld Entrance", "category": "Entrances", "map_x": 0.69, "map_y": 0.80},
    {"id": "box_office", "name": "To Box Office", "category": "Entrances", "map_x": 0.86, "map_y": 0.10},
    {"id": "main_entrance", "name": "Main Entrance", "category": "Entrances", "map_x": 0.50, "map_y": 0.87},
]


class PoiCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    category: str = Field(default="Custom POIs", max_length=120)
    map_x: float = Field(ge=0.0, le=1.0)
    map_y: float = Field(ge=0.0, le=1.0)
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    accuracy_meters: Optional[float] = None
    updated_by: Optional[str] = "android_admin"


class PoiUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    category: Optional[str] = Field(default=None, max_length=120)
    map_x: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    map_y: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    accuracy_meters: Optional[float] = None
    updated_by: Optional[str] = "android_admin"


class LocationUpdate(BaseModel):
    latitude: float
    longitude: float
    accuracy_meters: Optional[float] = None
    updated_by: Optional[str] = "android_admin"


class BeaconCreate(BaseModel):
    # The Android client currently lets the server generate the code.
    # code remains optional so older clients that provide one still work.
    code: Optional[str] = Field(default=None, max_length=24)
    name: Optional[str] = Field(default="Shared Location", max_length=120)
    latitude: float
    longitude: float
    accuracy_meters: Optional[float] = None
    updated_by: Optional[str] = "android_quickfinder"



class InferGpsRequest(BaseModel):
    anchor_ids: Optional[List[str]] = None
    overwrite_existing: bool = False
    min_anchors: int = 3


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_connection():
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def row_to_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "category": row["category"],
        "map_x": row["map_x"],
        "map_y": row["map_y"],

        # Android compatibility aliases.
        "mapX": row["map_x"],
        "mapY": row["map_y"],

        "is_custom": bool(row["is_custom"]),
        "latitude": row["latitude"],
        "longitude": row["longitude"],
        "accuracy_meters": row["accuracy_meters"],
        "updated_at": row["updated_at"],
        "updated_by": row["updated_by"],
        "gps_source": row["gps_source"],
    }


def beacon_row_to_dict(row: sqlite3.Row) -> dict:
    return {
        "code": row["code"],
        "id": row["code"],  # Android compatibility alias.
        "name": row["name"],
        "latitude": row["latitude"],
        "longitude": row["longitude"],
        "accuracy_meters": row["accuracy_meters"],
        "updated_at": row["updated_at"],
        "updated_by": row["updated_by"],
    }


def normalize_beacon_code(code: str) -> str:
    cleaned = "".join(ch for ch in code.upper().strip() if ch.isalnum())
    if not cleaned:
        raise HTTPException(status_code=400, detail="Missing beacon code")
    return cleaned[:24]


def generate_beacon_code(conn: sqlite3.Connection) -> str:
    # 6 hex chars is simple and readable enough for testing. Retry on the tiny
    # chance of collision.
    for _ in range(20):
        code = uuid4().hex[:6].upper()
        exists = conn.execute(
            "SELECT 1 FROM quickfinder_beacons WHERE code = ?",
            (code,),
        ).fetchone()
        if exists is None:
            return code

    # Practically unreachable fallback.
    return uuid4().hex[:10].upper()


def init_db():
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS pois (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                category TEXT NOT NULL,
                map_x REAL NOT NULL,
                map_y REAL NOT NULL,
                is_custom INTEGER NOT NULL DEFAULT 0,
                latitude REAL,
                longitude REAL,
                accuracy_meters REAL,
                updated_at TEXT,
                updated_by TEXT,
                gps_source TEXT
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS quickfinder_beacons (
                code TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                latitude REAL NOT NULL,
                longitude REAL NOT NULL,
                accuracy_meters REAL,
                updated_at TEXT NOT NULL,
                updated_by TEXT
            )
            """
        )

        # Lightweight migrations for older beacon.db files.
        existing_columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(pois)").fetchall()
        }

        if "gps_source" not in existing_columns:
            conn.execute("ALTER TABLE pois ADD COLUMN gps_source TEXT")

        # Seed/update built-in POIs.
        # This updates map_x/map_y from the seed list unless you have edited them.
        # If you want server/admin edits to survive redeploys, comment out the
        # map_x/map_y update lines in the ON CONFLICT block below.
        for poi in BUILT_IN_POIS:
            conn.execute(
                """
                INSERT INTO pois (
                    id, name, category, map_x, map_y, is_custom
                )
                VALUES (?, ?, ?, ?, ?, 0)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    category = excluded.category
                """,
                (
                    poi["id"],
                    poi["name"],
                    poi["category"],
                    poi["map_x"],
                    poi["map_y"],
                ),
            )

        conn.commit()


def solve_3x3(matrix, vector):
    """
    Solves matrix * x = vector using Gaussian elimination.
    No numpy required.
    """
    a = [
        [float(matrix[0][0]), float(matrix[0][1]), float(matrix[0][2]), float(vector[0])],
        [float(matrix[1][0]), float(matrix[1][1]), float(matrix[1][2]), float(vector[1])],
        [float(matrix[2][0]), float(matrix[2][1]), float(matrix[2][2]), float(vector[2])],
    ]

    n = 3

    for i in range(n):
        max_row = i
        for r in range(i + 1, n):
            if abs(a[r][i]) > abs(a[max_row][i]):
                max_row = r

        if abs(a[max_row][i]) < 1e-12:
            raise ValueError("Calibration anchors are invalid or too close together.")

        a[i], a[max_row] = a[max_row], a[i]

        pivot = a[i][i]
        for col in range(i, n + 1):
            a[i][col] /= pivot

        for r in range(n):
            if r != i:
                factor = a[r][i]
                for col in range(i, n + 1):
                    a[r][col] -= factor * a[i][col]

    return [a[0][3], a[1][3], a[2][3]]


def fit_affine_transform(anchor_rows):
    """
    Fits:
        lat = a * map_x + b * map_y + c
        lng = d * map_x + e * map_y + f

    With 3 anchors: exact fit.
    With 4+ anchors: least-squares fit using normal equations.
    """
    if len(anchor_rows) < 3:
        raise ValueError("At least 3 anchors are required.")

    ata = [
        [0.0, 0.0, 0.0],
        [0.0, 0.0, 0.0],
        [0.0, 0.0, 0.0],
    ]

    at_lat = [0.0, 0.0, 0.0]
    at_lng = [0.0, 0.0, 0.0]

    for row in anchor_rows:
        x = float(row["map_x"])
        y = float(row["map_y"])
        lat = float(row["latitude"])
        lng = float(row["longitude"])

        basis = [x, y, 1.0]

        for i in range(3):
            for j in range(3):
                ata[i][j] += basis[i] * basis[j]

            at_lat[i] += basis[i] * lat
            at_lng[i] += basis[i] * lng

    lat_coeffs = solve_3x3(ata, at_lat)
    lng_coeffs = solve_3x3(ata, at_lng)

    return {
        "lat": {
            "a": lat_coeffs[0],
            "b": lat_coeffs[1],
            "c": lat_coeffs[2],
        },
        "lng": {
            "a": lng_coeffs[0],
            "b": lng_coeffs[1],
            "c": lng_coeffs[2],
        },
    }


def apply_affine(transform, map_x, map_y):
    lat = (
        transform["lat"]["a"] * map_x
        + transform["lat"]["b"] * map_y
        + transform["lat"]["c"]
    )

    lng = (
        transform["lng"]["a"] * map_x
        + transform["lng"]["b"] * map_y
        + transform["lng"]["c"]
    )

    return lat, lng


def estimate_error_meters(actual_lat, actual_lng, estimated_lat, estimated_lng):
    meters_per_degree_lat = 111_320.0
    meters_per_degree_lng = 111_320.0 * math.cos(math.radians(actual_lat))

    d_lat = (estimated_lat - actual_lat) * meters_per_degree_lat
    d_lng = (estimated_lng - actual_lng) * meters_per_degree_lng

    return math.sqrt(d_lat * d_lat + d_lng * d_lng)


@app.on_event("startup")
def startup():
    init_db()


@app.get("/")
def root():
    return {
        "name": "Beacon Server",
        "status": "ok",
        "version": "3.0.0",
        "docs": "/docs",
    }


@app.get("/health")
def health():
    with get_connection() as conn:
        count = conn.execute("SELECT COUNT(*) AS count FROM pois").fetchone()["count"]
        beacon_count = conn.execute("SELECT COUNT(*) AS count FROM quickfinder_beacons").fetchone()["count"]

    return {
        "status": "ok",
        "database_path": DATABASE_PATH,
        "poi_count": count,
        "beacon_count": beacon_count,
        "time": now_iso(),
    }


@app.get("/pois")
def get_pois():
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM pois
            ORDER BY
                CASE category
                    WHEN 'Services & Amenities' THEN 1
                    WHEN 'Stages' THEN 2
                    WHEN 'Plazas' THEN 3
                    WHEN 'Entrances' THEN 4
                    WHEN 'Custom POIs' THEN 5
                    ELSE 6
                END,
                name COLLATE NOCASE ASC
            """
        ).fetchall()

    return [row_to_dict(row) for row in rows]


@app.get("/pois/{poi_id}")
def get_poi(poi_id: str):
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM pois WHERE id = ?",
            (poi_id,),
        ).fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail="POI not found")

    return row_to_dict(row)


@app.post("/pois")
def create_poi(payload: PoiCreate):
    poi_id = "custom_" + uuid4().hex[:12]
    timestamp = now_iso()

    gps_source = None
    if payload.latitude is not None and payload.longitude is not None:
        gps_source = "custom_created"

    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO pois (
                id, name, category, map_x, map_y, is_custom,
                latitude, longitude, accuracy_meters, updated_at, updated_by, gps_source
            )
            VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?)
            """,
            (
                poi_id,
                payload.name,
                payload.category or "Custom POIs",
                payload.map_x,
                payload.map_y,
                payload.latitude,
                payload.longitude,
                payload.accuracy_meters,
                timestamp,
                payload.updated_by,
                gps_source,
            ),
        )
        conn.commit()

        row = conn.execute(
            "SELECT * FROM pois WHERE id = ?",
            (poi_id,),
        ).fetchone()

    return row_to_dict(row)


@app.put("/pois/{poi_id}")
def update_poi(poi_id: str, payload: PoiUpdate):
    with get_connection() as conn:
        existing = conn.execute(
            "SELECT * FROM pois WHERE id = ?",
            (poi_id,),
        ).fetchone()

        if existing is None:
            raise HTTPException(status_code=404, detail="POI not found")

        name = payload.name if payload.name is not None else existing["name"]
        category = payload.category if payload.category is not None else existing["category"]
        map_x = payload.map_x if payload.map_x is not None else existing["map_x"]
        map_y = payload.map_y if payload.map_y is not None else existing["map_y"]

        latitude = payload.latitude if payload.latitude is not None else existing["latitude"]
        longitude = payload.longitude if payload.longitude is not None else existing["longitude"]
        accuracy_meters = (
            payload.accuracy_meters
            if payload.accuracy_meters is not None
            else existing["accuracy_meters"]
        )

        gps_source = existing["gps_source"]
        if payload.latitude is not None and payload.longitude is not None:
            gps_source = "manual_update"

        conn.execute(
            """
            UPDATE pois
            SET
                name = ?,
                category = ?,
                map_x = ?,
                map_y = ?,
                latitude = ?,
                longitude = ?,
                accuracy_meters = ?,
                updated_at = ?,
                updated_by = ?,
                gps_source = ?
            WHERE id = ?
            """,
            (
                name,
                category,
                map_x,
                map_y,
                latitude,
                longitude,
                accuracy_meters,
                now_iso(),
                payload.updated_by,
                gps_source,
                poi_id,
            ),
        )
        conn.commit()

        row = conn.execute(
            "SELECT * FROM pois WHERE id = ?",
            (poi_id,),
        ).fetchone()

    return row_to_dict(row)


@app.put("/pois/{poi_id}/location")
def update_poi_location(poi_id: str, payload: LocationUpdate):
    with get_connection() as conn:
        existing = conn.execute(
            "SELECT * FROM pois WHERE id = ?",
            (poi_id,),
        ).fetchone()

        if existing is None:
            raise HTTPException(status_code=404, detail="POI not found")

        conn.execute(
            """
            UPDATE pois
            SET
                latitude = ?,
                longitude = ?,
                accuracy_meters = ?,
                updated_at = ?,
                updated_by = ?,
                gps_source = ?
            WHERE id = ?
            """,
            (
                payload.latitude,
                payload.longitude,
                payload.accuracy_meters,
                now_iso(),
                payload.updated_by,
                "manual_location",
                poi_id,
            ),
        )
        conn.commit()

        row = conn.execute(
            "SELECT * FROM pois WHERE id = ?",
            (poi_id,),
        ).fetchone()

    return row_to_dict(row)


@app.delete("/pois/{poi_id}")
def delete_poi(poi_id: str):
    with get_connection() as conn:
        existing = conn.execute(
            "SELECT * FROM pois WHERE id = ?",
            (poi_id,),
        ).fetchone()

        if existing is None:
            raise HTTPException(status_code=404, detail="POI not found")

        if not bool(existing["is_custom"]):
            raise HTTPException(
                status_code=403,
                detail="Built-in POIs cannot be deleted",
            )

        conn.execute(
            "DELETE FROM pois WHERE id = ?",
            (poi_id,),
        )
        conn.commit()

    return {
        "deleted": True,
        "id": poi_id,
    }


@app.post("/beacons")
def create_quickfinder_beacon(payload: BeaconCreate):
    timestamp = now_iso()

    with get_connection() as conn:
        code = normalize_beacon_code(payload.code) if payload.code else generate_beacon_code(conn)
        name = (payload.name or "Shared Location").strip() or "Shared Location"

        conn.execute(
            """
            INSERT INTO quickfinder_beacons (
                code, name, latitude, longitude, accuracy_meters, updated_at, updated_by
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(code) DO UPDATE SET
                name = excluded.name,
                latitude = excluded.latitude,
                longitude = excluded.longitude,
                accuracy_meters = excluded.accuracy_meters,
                updated_at = excluded.updated_at,
                updated_by = excluded.updated_by
            """,
            (
                code,
                name,
                payload.latitude,
                payload.longitude,
                payload.accuracy_meters,
                timestamp,
                payload.updated_by,
            ),
        )
        conn.commit()

        row = conn.execute(
            "SELECT * FROM quickfinder_beacons WHERE code = ?",
            (code,),
        ).fetchone()

    return beacon_row_to_dict(row)


@app.get("/beacons/{code}")
def get_quickfinder_beacon(code: str):
    clean_code = normalize_beacon_code(code)

    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM quickfinder_beacons WHERE code = ?",
            (clean_code,),
        ).fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail="Beacon code not found")

    return beacon_row_to_dict(row)


@app.delete("/beacons/{code}")
def delete_quickfinder_beacon(code: str):
    clean_code = normalize_beacon_code(code)

    with get_connection() as conn:
        existing = conn.execute(
            "SELECT * FROM quickfinder_beacons WHERE code = ?",
            (clean_code,),
        ).fetchone()

        if existing is None:
            raise HTTPException(status_code=404, detail="Beacon code not found")

        conn.execute(
            "DELETE FROM quickfinder_beacons WHERE code = ?",
            (clean_code,),
        )
        conn.commit()

    return {"deleted": True, "code": clean_code}


@app.post("/calibration/infer-gps")
def infer_gps_from_map(payload: InferGpsRequest):
    timestamp = now_iso()

    with get_connection() as conn:
        if payload.anchor_ids:
            if len(payload.anchor_ids) < 3:
                raise HTTPException(
                    status_code=400,
                    detail="At least 3 anchor_ids are required.",
                )

            placeholders = ",".join(["?"] * len(payload.anchor_ids))
            anchor_rows = conn.execute(
                f"""
                SELECT *
                FROM pois
                WHERE id IN ({placeholders})
                  AND latitude IS NOT NULL
                  AND longitude IS NOT NULL
                  AND map_x IS NOT NULL
                  AND map_y IS NOT NULL
                """,
                payload.anchor_ids,
            ).fetchall()

            found_anchor_ids = {row["id"] for row in anchor_rows}
            missing_anchor_ids = [
                anchor_id for anchor_id in payload.anchor_ids
                if anchor_id not in found_anchor_ids
            ]
        else:
            anchor_rows = conn.execute(
                """
                SELECT *
                FROM pois
                WHERE latitude IS NOT NULL
                  AND longitude IS NOT NULL
                  AND map_x IS NOT NULL
                  AND map_y IS NOT NULL
                """
            ).fetchall()
            missing_anchor_ids = []

        if len(anchor_rows) < payload.min_anchors:
            raise HTTPException(
                status_code=400,
                detail={
                    "message": f"Need at least {payload.min_anchors} anchor POIs with map_x/map_y and latitude/longitude.",
                    "found_anchor_count": len(anchor_rows),
                    "missing_or_incomplete_anchor_ids": missing_anchor_ids,
                },
            )

        if len(anchor_rows) < 3:
            raise HTTPException(
                status_code=400,
                detail="At least 3 anchors are required for GPS inference.",
            )

        try:
            transform = fit_affine_transform(anchor_rows)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        if payload.overwrite_existing:
            target_rows = conn.execute(
                """
                SELECT *
                FROM pois
                WHERE map_x IS NOT NULL
                  AND map_y IS NOT NULL
                """
            ).fetchall()
        else:
            target_rows = conn.execute(
                """
                SELECT *
                FROM pois
                WHERE map_x IS NOT NULL
                  AND map_y IS NOT NULL
                  AND (latitude IS NULL OR longitude IS NULL)
                """
            ).fetchall()

        updated = []

        for row in target_rows:
            estimated_lat, estimated_lng = apply_affine(
                transform,
                float(row["map_x"]),
                float(row["map_y"]),
            )

            conn.execute(
                """
                UPDATE pois
                SET
                    latitude = ?,
                    longitude = ?,
                    accuracy_meters = ?,
                    updated_at = ?,
                    updated_by = ?,
                    gps_source = ?
                WHERE id = ?
                """,
                (
                    estimated_lat,
                    estimated_lng,
                    25.0,
                    timestamp,
                    "gps_inference",
                    "inferred_from_map_anchors",
                    row["id"],
                ),
            )

            updated.append({
                "id": row["id"],
                "name": row["name"],
                "category": row["category"],
                "map_x": row["map_x"],
                "map_y": row["map_y"],
                "estimated_latitude": estimated_lat,
                "estimated_longitude": estimated_lng,
            })

        diagnostics = []

        for row in anchor_rows:
            estimated_lat, estimated_lng = apply_affine(
                transform,
                float(row["map_x"]),
                float(row["map_y"]),
            )

            error_meters = estimate_error_meters(
                float(row["latitude"]),
                float(row["longitude"]),
                estimated_lat,
                estimated_lng,
            )

            diagnostics.append({
                "id": row["id"],
                "name": row["name"],
                "actual_latitude": row["latitude"],
                "actual_longitude": row["longitude"],
                "estimated_latitude": estimated_lat,
                "estimated_longitude": estimated_lng,
                "error_meters": error_meters,
            })

        conn.commit()

    return {
        "ok": True,
        "anchor_count": len(anchor_rows),
        "missing_or_incomplete_anchor_ids": missing_anchor_ids,
        "updated_count": len(updated),
        "overwrite_existing": payload.overwrite_existing,
        "transform": transform,
        "anchor_diagnostics": diagnostics,
        "updated": updated,
    }


@app.post("/calibration/clear-inferred-gps")
def clear_inferred_gps():
    """
    Useful during testing.
    Clears only GPS values created by the inference endpoint.
    Manually recorded GPS remains untouched.
    """
    with get_connection() as conn:
        result = conn.execute(
            """
            UPDATE pois
            SET
                latitude = NULL,
                longitude = NULL,
                accuracy_meters = NULL,
                updated_at = ?,
                updated_by = ?,
                gps_source = NULL
            WHERE gps_source = ?
            """,
            (
                now_iso(),
                "clear_inferred_gps",
                "inferred_from_map_anchors",
            ),
        )
        conn.commit()

    return {
        "ok": True,
        "cleared_count": result.rowcount,
    }
