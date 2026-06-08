from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from typing import Optional, List
import sqlite3
import os
import math
from datetime import datetime, timezone
from uuid import uuid4


DATABASE_PATH = os.getenv("DATABASE_PATH", "beacon.db")
STATIC_DIR = os.getenv("STATIC_DIR", "static")
MAPS_DIR = os.path.join(STATIC_DIR, "maps")

os.makedirs(MAPS_DIR, exist_ok=True)

MAP_EXTENSIONS = [".png", ".jpg", ".jpeg", ".webp"]


def find_map_url(base_name: str) -> str:
    """
    Returns the first existing static map URL for a base filename.

    This lets Dash work with any of these files:
        static/maps/lib_map.png
        static/maps/lib_map.jpg
        static/maps/lib_map.jpeg
        static/maps/lib_map.webp

    The important part is that the base name stays consistent.
    """
    for ext in MAP_EXTENSIONS:
        candidate = os.path.join(MAPS_DIR, f"{base_name}{ext}")
        if os.path.exists(candidate):
            return f"/static/maps/{base_name}{ext}"

    # Predictable fallback. Dash will show the styled placeholder if the image fails.
    return f"/static/maps/{base_name}.png"


def map_file_status(base_name: str) -> dict:
    found = []
    for ext in MAP_EXTENSIONS:
        candidate = os.path.join(MAPS_DIR, f"{base_name}{ext}")
        if os.path.exists(candidate):
            found.append(f"{base_name}{ext}")

    return {
        "base_name": base_name,
        "map_url": find_map_url(base_name),
        "found_files": found,
        "exists": bool(found),
    }


app = FastAPI(title="Beacon Server", version="3.2.2")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


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
    event_id: Optional[str] = Field(default="lib_2026", max_length=80)
    name: str = Field(min_length=1, max_length=120)
    category: str = Field(default="Custom POIs", max_length=120)
    map_x: float = Field(ge=0.0, le=1.0)
    map_y: float = Field(ge=0.0, le=1.0)
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    accuracy_meters: Optional[float] = None
    updated_by: Optional[str] = "android_admin"


class PoiUpdate(BaseModel):
    event_id: Optional[str] = Field(default=None, max_length=80)
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


class WrstopsGateCreate(BaseModel):
    name: str = Field(default="Gate", min_length=1, max_length=120)
    map_x: float = Field(ge=0.0, le=1.0)
    map_y: float = Field(ge=0.0, le=1.0)
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    accuracy_meters: Optional[float] = None
    scan_count: Optional[int] = 0
    connection_status: Optional[str] = Field(default="ONLINE", max_length=40)
    ip_address: Optional[str] = Field(default=None, max_length=80)
    override_status: Optional[str] = Field(default="NORMAL", max_length=40)
    updated_by: Optional[str] = "android_wrstops"


class WrstopsGateUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    map_x: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    map_y: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    accuracy_meters: Optional[float] = None
    scan_count: Optional[int] = None
    connection_status: Optional[str] = Field(default=None, max_length=40)
    ip_address: Optional[str] = Field(default=None, max_length=80)
    override_status: Optional[str] = Field(default=None, max_length=40)
    updated_by: Optional[str] = "android_wrstops"




class CalibrationAnchorCreate(BaseModel):
    map_x: float = Field(ge=0.0, le=1.0)
    map_y: float = Field(ge=0.0, le=1.0)
    latitude: float
    longitude: float
    accuracy_meters: Optional[float] = None
    created_by: Optional[str] = "android_survey"


class SurveyPathPointCreate(BaseModel):
    seq: int
    latitude: float
    longitude: float
    accuracy_meters: Optional[float] = None
    timestamp: Optional[str] = None


class SurveyPathCreate(BaseModel):
    name: str = Field(default="Survey Path", min_length=1, max_length=160)
    survey_mode: str = Field(default="direct_path", max_length=40)
    path_type: str = Field(default="guest", max_length=40)
    start_map_x: float = Field(ge=0.0, le=1.0)
    start_map_y: float = Field(ge=0.0, le=1.0)
    end_map_x: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    end_map_y: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    distance_meters: Optional[float] = 0.0
    created_by: Optional[str] = "android_survey"
    points: List[SurveyPathPointCreate] = []


class SurveyPathUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=160)
    survey_mode: Optional[str] = Field(default=None, max_length=40)
    path_type: Optional[str] = Field(default=None, max_length=40)
    start_map_x: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    start_map_y: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    end_map_x: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    end_map_y: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    distance_meters: Optional[float] = None
    updated_by: Optional[str] = "dash_editor"


class WifiSweepSampleCreate(BaseModel):
    seq: int
    latitude: float
    longitude: float
    accuracy_meters: Optional[float] = None
    map_x: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    map_y: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    ssid: Optional[str] = Field(default=None, max_length=160)
    bssid: Optional[str] = Field(default=None, max_length=80)
    rssi_dbm: int
    frequency_mhz: Optional[int] = None
    timestamp: Optional[str] = None


class WifiSweepCreate(BaseModel):
    name: str = Field(default="WiFi Sweep", min_length=1, max_length=160)
    target_ssid: Optional[str] = Field(default=None, max_length=160)
    target_bssid: Optional[str] = Field(default=None, max_length=80)
    created_by: Optional[str] = "android_wifi_sweeper"
    samples: List[WifiSweepSampleCreate] = []

class InferGpsRequest(BaseModel):
    anchor_ids: Optional[List[str]] = None
    overwrite_existing: bool = False
    min_anchors: int = 3


class InferMapPositionRequest(BaseModel):
    latitude: float
    longitude: float
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
        "event_id": row["event_id"],
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


def wrstops_gate_row_to_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "event_id": row["event_id"],
        "name": row["name"],
        "map_x": row["map_x"],
        "map_y": row["map_y"],
        # Android compatibility aliases.
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




def calibration_anchor_row_to_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "event_id": row["event_id"],
        "map_x": row["map_x"],
        "map_y": row["map_y"],
        "mapX": row["map_x"],
        "mapY": row["map_y"],
        "latitude": row["latitude"],
        "longitude": row["longitude"],
        "accuracy_meters": row["accuracy_meters"],
        "created_at": row["created_at"],
        "created_by": row["created_by"],
    }


def survey_path_row_to_dict(row: sqlite3.Row, points=None) -> dict:
    payload = {
        "id": row["id"],
        "event_id": row["event_id"],
        "name": row["name"],
        "survey_mode": row["survey_mode"],
        "path_type": row["path_type"],
        "start_map_x": row["start_map_x"],
        "start_map_y": row["start_map_y"],
        "end_map_x": row["end_map_x"],
        "end_map_y": row["end_map_y"],
        "distance_meters": row["distance_meters"],
        "point_count": row["point_count"],
        "created_at": row["created_at"],
        "created_by": row["created_by"],
    }
    if points is not None:
        payload["points"] = points
    return payload


def survey_point_row_to_dict(row: sqlite3.Row) -> dict:
    return {
        "seq": row["seq"],
        "latitude": row["latitude"],
        "longitude": row["longitude"],
        "accuracy_meters": row["accuracy_meters"],
        "timestamp": row["timestamp"],
    }


def wifi_sweep_row_to_dict(row: sqlite3.Row, samples=None) -> dict:
    payload = {
        "id": row["id"],
        "event_id": row["event_id"],
        "name": row["name"],
        "target_ssid": row["target_ssid"],
        "target_bssid": row["target_bssid"],
        "sample_count": row["sample_count"],
        "created_at": row["created_at"],
        "created_by": row["created_by"],
    }
    if samples is not None:
        payload["samples"] = samples
    return payload


def wifi_sample_row_to_dict(row: sqlite3.Row) -> dict:
    return {
        "seq": row["seq"],
        "latitude": row["latitude"],
        "longitude": row["longitude"],
        "accuracy_meters": row["accuracy_meters"],
        "map_x": row["map_x"],
        "map_y": row["map_y"],
        "mapX": row["map_x"],
        "mapY": row["map_y"],
        "ssid": row["ssid"],
        "bssid": row["bssid"],
        "rssi_dbm": row["rssi_dbm"],
        "frequency_mhz": row["frequency_mhz"],
        "timestamp": row["timestamp"],
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
                event_id TEXT NOT NULL DEFAULT 'lib_2026',
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

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS wrstops_gates (
                id TEXT PRIMARY KEY,
                event_id TEXT NOT NULL,
                name TEXT NOT NULL,
                map_x REAL NOT NULL,
                map_y REAL NOT NULL,
                latitude REAL,
                longitude REAL,
                accuracy_meters REAL,
                scan_count INTEGER NOT NULL DEFAULT 0,
                connection_status TEXT NOT NULL DEFAULT 'ONLINE',
                ip_address TEXT,
                override_status TEXT NOT NULL DEFAULT 'NORMAL',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                updated_by TEXT
            )
            """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_wrstops_gates_event_id
            ON wrstops_gates(event_id)
            """
        )

        existing_gate_columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(wrstops_gates)").fetchall()
        }

        if "latitude" not in existing_gate_columns:
            conn.execute("ALTER TABLE wrstops_gates ADD COLUMN latitude REAL")
        if "longitude" not in existing_gate_columns:
            conn.execute("ALTER TABLE wrstops_gates ADD COLUMN longitude REAL")
        if "accuracy_meters" not in existing_gate_columns:
            conn.execute("ALTER TABLE wrstops_gates ADD COLUMN accuracy_meters REAL")


        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS map_calibration_anchors (
                id TEXT PRIMARY KEY,
                event_id TEXT NOT NULL,
                map_x REAL NOT NULL,
                map_y REAL NOT NULL,
                latitude REAL NOT NULL,
                longitude REAL NOT NULL,
                accuracy_meters REAL,
                created_at TEXT NOT NULL,
                created_by TEXT
            )
            """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_map_calibration_event_id
            ON map_calibration_anchors(event_id)
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS survey_paths (
                id TEXT PRIMARY KEY,
                event_id TEXT NOT NULL,
                name TEXT NOT NULL,
                survey_mode TEXT NOT NULL,
                path_type TEXT NOT NULL,
                start_map_x REAL NOT NULL,
                start_map_y REAL NOT NULL,
                end_map_x REAL,
                end_map_y REAL,
                distance_meters REAL,
                point_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                created_by TEXT
            )
            """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_survey_paths_event_id
            ON survey_paths(event_id)
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS survey_path_points (
                id TEXT PRIMARY KEY,
                path_id TEXT NOT NULL,
                seq INTEGER NOT NULL,
                latitude REAL NOT NULL,
                longitude REAL NOT NULL,
                accuracy_meters REAL,
                timestamp TEXT,
                FOREIGN KEY(path_id) REFERENCES survey_paths(id) ON DELETE CASCADE
            )
            """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_survey_path_points_path_id
            ON survey_path_points(path_id)
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS wifi_sweeps (
                id TEXT PRIMARY KEY,
                event_id TEXT NOT NULL,
                name TEXT NOT NULL,
                target_ssid TEXT,
                target_bssid TEXT,
                sample_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                created_by TEXT
            )
            """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_wifi_sweeps_event_id
            ON wifi_sweeps(event_id)
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS wifi_sweep_samples (
                id TEXT PRIMARY KEY,
                sweep_id TEXT NOT NULL,
                seq INTEGER NOT NULL,
                latitude REAL NOT NULL,
                longitude REAL NOT NULL,
                accuracy_meters REAL,
                map_x REAL,
                map_y REAL,
                ssid TEXT,
                bssid TEXT,
                rssi_dbm INTEGER NOT NULL,
                frequency_mhz INTEGER,
                timestamp TEXT,
                FOREIGN KEY(sweep_id) REFERENCES wifi_sweeps(id) ON DELETE CASCADE
            )
            """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_wifi_sweep_samples_sweep_id
            ON wifi_sweep_samples(sweep_id)
            """
        )


        # Lightweight migrations for older beacon.db files.
        existing_columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(pois)").fetchall()
        }

        if "gps_source" not in existing_columns:
            conn.execute("ALTER TABLE pois ADD COLUMN gps_source TEXT")

        if "event_id" not in existing_columns:
            conn.execute("ALTER TABLE pois ADD COLUMN event_id TEXT NOT NULL DEFAULT 'lib_2026'")

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_pois_event_id
            ON pois(event_id)
            """
        )

        # Seed/update built-in POIs.
        # This updates map_x/map_y from the seed list unless you have edited them.
        # If you want server/admin edits to survive redeploys, comment out the
        # map_x/map_y update lines in the ON CONFLICT block below.
        for poi in BUILT_IN_POIS:
            conn.execute(
                """
                INSERT INTO pois (
                    id, event_id, name, category, map_x, map_y, is_custom
                )
                VALUES (?, 'lib_2026', ?, ?, ?, ?, 0)
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


def apply_inverse_affine(transform, latitude, longitude):
    """
    Converts GPS latitude/longitude back into normalized map coordinates.

    This is the inverse of:
        lat = a*x + b*y + c
        lng = d*x + e*y + f
    """
    a = float(transform["lat"]["a"])
    b = float(transform["lat"]["b"])
    c = float(transform["lat"]["c"])
    d = float(transform["lng"]["a"])
    e = float(transform["lng"]["b"])
    f = float(transform["lng"]["c"])

    det = a * e - b * d
    if abs(det) < 1e-18:
        raise ValueError("Calibration transform cannot be inverted. Add wider-spaced anchors.")

    lat_delta = float(latitude) - c
    lng_delta = float(longitude) - f

    map_x = (lat_delta * e - b * lng_delta) / det
    map_y = (a * lng_delta - lat_delta * d) / det
    return map_x, map_y


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
        wrstops_gate_count = conn.execute("SELECT COUNT(*) AS count FROM wrstops_gates").fetchone()["count"]
        wifi_sweep_count = conn.execute("SELECT COUNT(*) AS count FROM wifi_sweeps").fetchone()["count"]

    return {
        "status": "ok",
        "database_path": DATABASE_PATH,
        "poi_count": count,
        "beacon_count": beacon_count,
        "wrstops_gate_count": wrstops_gate_count,
        "wifi_sweep_count": wifi_sweep_count,
        "maps": [map_file_status(event["map_name"]) for event in EVENTS],
        "time": now_iso(),
    }


EVENTS = [
    {"id": "lib_2026", "name": "LIB '26", "map_name": "lib_map", "description": "LIB event map and POI set."},
    {"id": "freedom_250", "name": "Freedom 250", "map_name": "f250_map", "description": "Freedom 250 White House field test event."},
]


def get_event_config(event_id: str) -> dict:
    for event in EVENTS:
        if event["id"] == event_id:
            event_copy = dict(event)
            event_copy["map_url"] = find_map_url(event_copy["map_name"])
            return event_copy

    raise HTTPException(status_code=404, detail="Event not found")


@app.get("/events")
def get_events():
    return [get_event_config(event["id"]) for event in EVENTS]


@app.get("/events/{event_id}")
def get_event(event_id: str):
    return get_event_config(event_id)


@app.get("/maps/status")
def maps_status():
    return [map_file_status(event["map_name"]) for event in EVENTS]


@app.get("/dash", response_class=HTMLResponse)
def dash():
    return HTMLResponse(DASH_HTML)


DASH_HTML = r'''
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Beacon Dash</title>
  <style>
    :root{--bg:#08111d;--panel:#101c2b;--panel2:#152338;--muted:#8ea2b8;--text:#f5f8fc;--line:rgba(255,255,255,.12);--blue:#5db7ff;--green:#6df7a7;--yellow:#ffd166;--red:#ff6b6b}
    *{box-sizing:border-box} body{margin:0;font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif;color:var(--text);background:radial-gradient(circle at top left,#14365a 0,var(--bg) 36rem)}
    button,input,select,textarea{font:inherit} button{border:1px solid var(--line);border-radius:12px;background:#1d3552;color:var(--text);padding:9px 12px;cursor:pointer} button:hover{filter:brightness(1.12)} button.primary{background:#1565c0;border-color:#5db7ff} button.danger{background:#6b1e25;border-color:#ff6b6b} button.ghost{background:transparent}
    input,select,textarea{width:100%;border:1px solid var(--line);border-radius:10px;background:#07101b;color:var(--text);padding:10px;outline:none} textarea{min-height:120px;font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:13px} label{display:block;font-size:12px;color:var(--muted);margin:8px 0 5px}
    .app{max-width:1500px;margin:0 auto;padding:18px}.top{display:flex;justify-content:space-between;gap:16px;align-items:flex-start;flex-wrap:wrap;margin-bottom:16px}.brand h1{margin:0;font-size:30px;letter-spacing:.05em}.brand p{margin:4px 0 0;color:var(--muted)}
    .events,.tabs{display:flex;gap:8px;flex-wrap:wrap}.event.active,.tab.active{outline:2px solid var(--green);background:#12344a}.event b{display:block}.event span{font-size:12px;color:var(--muted)}
    .layout{display:grid;grid-template-columns:minmax(420px,1.15fr) minmax(360px,.85fr);gap:16px}@media(max-width:980px){.layout{grid-template-columns:1fr}}
    .panel{background:rgba(16,28,43,.94);border:1px solid var(--line);border-radius:18px;box-shadow:0 14px 32px rgba(0,0,0,.28);overflow:hidden}.panelHeader{padding:13px 15px;border-bottom:1px solid var(--line);display:flex;justify-content:space-between;gap:10px;align-items:center}.panelHeader h2{margin:0;font-size:18px}.panelBody{padding:14px}.muted{color:var(--muted);font-size:12px}.status{color:#b7d7ff;font-size:12px;margin-top:8px;white-space:pre-wrap}.row{display:flex;gap:8px;align-items:center;flex-wrap:wrap}.row>*{flex:1}.list{display:flex;flex-direction:column;gap:8px;max-height:520px;overflow:auto}.card{background:var(--panel2);border:1px solid var(--line);border-radius:14px;padding:10px}.card.selected{outline:2px solid var(--green);background:#173a35}.card h3{margin:0 0 4px;font-size:15px}.card p{margin:0 0 8px;color:var(--muted);font-size:12px}.small{font-size:11px;color:var(--muted)}
    .mapWrap{position:relative;width:100%;aspect-ratio:16/9;background:#0d1724;border-radius:14px;overflow:hidden;border:1px solid var(--line)}.mapWrap img{position:absolute;inset:0;width:100%;height:100%;object-fit:contain}.placeholder{position:absolute;inset:0;background:linear-gradient(135deg,#29475e,#17482a);display:flex;align-items:center;justify-content:center;color:#d8edf8}.marker{position:absolute;transform:translate(-50%,-50%);border-radius:50%;border:2px solid #fff;box-shadow:0 1px 8px rgba(0,0,0,.5);cursor:pointer}.marker.selected{outline:3px solid var(--green);outline-offset:3px}.poi{width:16px;height:16px;background:#e53935}.gate{width:18px;height:18px;background:#9c27b0}.anchor{width:14px;height:14px;background:#00e5ff}.survey{width:18px;height:18px;background:#ffd166}.heat{width:30px;height:30px;border:0;opacity:.62;mix-blend-mode:screen}.pathLine{position:absolute;left:0;top:0;width:100%;height:100%;pointer-events:none}.legend{display:flex;align-items:center;gap:8px;font-size:11px;color:var(--muted);margin-top:8px}.grad{width:160px;height:14px;border-radius:10px;background:linear-gradient(90deg,#00e676,#9cff57,#ffeb3b,#ff9800,#ff1744)}
    .pathSvgLine{stroke:#ffd166;stroke-width:5;stroke-linecap:round;fill:none;opacity:.78}.pathSvgLine.selected{stroke:#6df7a7;stroke-width:8;opacity:1}.hidden{display:none!important}
  </style>
</head>
<body>
<div class="app">
  <div class="top"><div class="brand"><h1>Beacon Dash</h1><p>Event admin, Wi-Fi heatmaps, and remote surveying.</p></div><div class="events" id="eventButtons"></div></div>
  <div class="tabs" id="tabs"><button class="tab active" data-tab="overview">Overview</button><button class="tab" data-tab="wifi">Wi-Fi Heatmaps</button><button class="tab" data-tab="remoteSurvey">Remote Survey</button><button class="tab" data-tab="calibration">Calibration</button><button class="tab" data-tab="data">POIs / Survey / WRSTOPS</button></div><br />
  <div class="layout">
    <div class="panel"><div class="panelHeader"><h2 id="mapTitle">Map</h2><button onclick="refreshAll()">Refresh</button></div><div class="panelBody"><div class="mapWrap" id="mapWrap"><div class="placeholder">Map loading...</div><svg class="pathLine" id="pathSvg" viewBox="0 0 1000 562" preserveAspectRatio="none"></svg></div><div class="legend"><div class="grad"></div><span>Wi-Fi signal: green strongest → red weakest</span></div><div class="status" id="status">Ready.</div></div></div>
    <div class="panel"><div class="panelHeader"><h2 id="toolTitle">Overview</h2></div><div class="panelBody">
      <section id="tab-overview"><p class="muted">Click a POI, calibration anchor, or survey path directly on the map to select it. The matching item highlights in the list on the right and expands with edit/delete controls.</p><div class="card"><h3>Selection behavior</h3><p>POIs and survey paths are now linked both ways: map → list and list → map.</p></div></section>
      <section id="tab-wifi" class="hidden"><div class="row"><button onclick="loadWifiSweeps()">Refresh Sweeps</button><button class="ghost" onclick="clearOverlay(); drawBase();">Clear Layer</button></div><br /><div class="list" id="wifiList"></div></section>
      <section id="tab-remoteSurvey" class="hidden"><label>Survey name</label><input id="rsName" placeholder="North Gate to Box Office" /><div class="row"><div><label>Mode</label><select id="rsMode"><option value="direct_path">Direct Path</option><option value="area_walk">Area Walk</option></select></div><div><label>Path Type</label><select id="rsType"><option value="guest">Guest</option><option value="staff">Staff</option><option value="cart">Cart</option><option value="restricted">Restricted</option><option value="emergency">Emergency</option></select></div></div><div class="row"><button onclick="mapClickMode='surveyStart'; setStatus('Click map for survey start point.')">Set Start on Map</button><button onclick="mapClickMode='surveyEnd'; setStatus('Click map for survey destination/end point.')">Set End on Map</button></div><div class="small" id="rsMapInfo">Start/end map anchors not set.</div><label>GPS coordinates from Google Maps</label><textarea id="rsPoints" placeholder="38.896889, -77.036583\n38.896700, -77.036200\n38.896500, -77.035900"></textarea><div class="row"><button class="primary" onclick="saveRemoteSurvey()">Save Survey Path</button><button onclick="previewRemoteSurvey()">Preview</button></div></section>
      <section id="tab-calibration" class="hidden"><p class="muted">Remote calibration lets you click a known map point, paste its latitude/longitude from Google Maps, and save it as a calibration anchor.</p><div class="row"><button onclick="mapClickMode='calibration'; setStatus('Click map where this GPS coordinate belongs.')">Set Map Point</button><button onclick="loadAnchors()">Refresh Anchors</button></div><div class="small" id="calMapInfo">No map point selected.</div><label>Latitude</label><input id="calLat" placeholder="38.896889" /><label>Longitude</label><input id="calLng" placeholder="-77.036583" /><div class="row"><button class="primary" onclick="saveCalibrationAnchor()">Save Anchor</button></div><br /><div class="list" id="anchorList"></div></section>
      <section id="tab-data" class="hidden"><div class="row"><button onclick="loadPois()">POIs</button><button onclick="loadSurveyPaths()">Survey Paths</button><button onclick="loadGates()">WRSTOPS</button><button class="primary" onclick="startAddPoi()">+ POI</button><button class="primary" onclick="startAddGate()">+ Gate</button></div><br /><div id="dataList" class="list"></div></section>
    </div></div>
  </div>
</div>
<script>
let events=[], currentEvent=null, currentTab='overview', mapClickMode=null, dataMode='pois';
let mapAnchors=[], pois=[], gates=[], wifiSweeps=[], surveyPaths=[];
let remoteSurveyStart=null, remoteSurveyEnd=null, calibrationMapPoint=null;
let selectedKind=null, selectedId=null;
function setStatus(t){document.getElementById('status').textContent=t;}
function api(path, opts={}){return fetch(path,{headers:{'Content-Type':'application/json'},...opts}).then(async r=>{if(!r.ok){throw new Error(await r.text())} return r.status===204?null:r.json()})}
function setSelected(kind,id){selectedKind=kind; selectedId=id;}
function pct(n){return (n*100).toFixed(2)+'%'}
function escapeHtml(s){return String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}
function n3(v){return Number(v??0).toFixed(3)} function n4(v){return Number(v??0).toFixed(4)}
function setTab(tab, autoLoad=true){currentTab=tab; document.querySelectorAll('.tab').forEach(b=>b.classList.toggle('active',b.dataset.tab===tab)); document.querySelectorAll('[id^="tab-"]').forEach(s=>s.classList.add('hidden')); document.getElementById('tab-'+tab).classList.remove('hidden'); document.getElementById('toolTitle').textContent={overview:'Overview',wifi:'Wi-Fi Heatmaps',remoteSurvey:'Remote Survey',calibration:'Calibration',data:'POIs / Survey / WRSTOPS'}[tab]||tab; clearOverlay(); if(!autoLoad)return; if(tab==='wifi')loadWifiSweeps(); if(tab==='calibration')loadAnchors(); if(tab==='data')loadPois();}
document.querySelectorAll('.tab').forEach(b=>b.onclick=()=>setTab(b.dataset.tab));
function marker(x,y,cls,title,onclick){const el=document.createElement('div'); el.className='marker '+cls; if(selectedKind&&title&&title.includes(selectedId))el.classList.add('selected'); el.style.left=pct(x); el.style.top=pct(y); el.title=title||''; if(onclick){el.onclick=(ev)=>{ev.stopPropagation(); onclick();};} document.getElementById('mapWrap').appendChild(el); return el;}
function wifiColor(rssi){if(rssi>=-50)return '#00e676'; if(rssi>=-60)return '#9cff57'; if(rssi>=-67)return '#ffeb3b'; if(rssi>=-75)return '#ff9800'; return '#ff1744'}
function heat(x,y,rssi,title){const el=marker(x,y,'heat',title); el.style.background=wifiColor(rssi); el.style.boxShadow=`0 0 24px 10px ${wifiColor(rssi)}`; return el;}
function clearOverlay(){document.querySelectorAll('.marker').forEach(e=>e.remove()); document.getElementById('pathSvg').innerHTML='';}
function drawBase(){clearOverlay(); pois.forEach(p=>marker(p.map_x,p.map_y,'poi',`${p.id} ${p.name}`,()=>selectPoi(p.id))); gates.forEach(g=>marker(g.map_x,g.map_y,'gate',`${g.id} ${g.name}`,()=>selectGate(g.id))); mapAnchors.forEach(a=>marker(a.map_x,a.map_y,'anchor',`anchor ${a.id}`,()=>selectAnchor(a.id))); if(dataMode==='survey')drawSurveyPaths();}
function mapXY(evt){const rect=document.getElementById('mapWrap').getBoundingClientRect(); return {x:Math.max(0,Math.min(1,(evt.clientX-rect.left)/rect.width)), y:Math.max(0,Math.min(1,(evt.clientY-rect.top)/rect.height))}}
document.getElementById('mapWrap').addEventListener('click', e=>{const p=mapXY(e); if(!mapClickMode)return; if(mapClickMode==='surveyStart'){remoteSurveyStart=p; marker(p.x,p.y,'anchor','Survey start'); updateSurveyInfo(); setStatus('Survey start set.');} if(mapClickMode==='surveyEnd'){remoteSurveyEnd=p; marker(p.x,p.y,'anchor','Survey end'); updateSurveyInfo(); setStatus('Survey end set.');} if(mapClickMode==='calibration'){calibrationMapPoint=p; marker(p.x,p.y,'anchor','New calibration anchor'); document.getElementById('calMapInfo').textContent=`Map point: ${p.x.toFixed(4)}, ${p.y.toFixed(4)}`; setStatus('Calibration map point set.');} if(mapClickMode==='movePoi'&&selectedKind==='poi'){document.getElementById('editPoiMapX').value=p.x.toFixed(4); document.getElementById('editPoiMapY').value=p.y.toFixed(4); setStatus('POI map position updated in editor. Click Save POI.');} if(mapClickMode==='moveGate'&&selectedKind==='gate'){document.getElementById('editGateMapX').value=p.x.toFixed(4); document.getElementById('editGateMapY').value=p.y.toFixed(4); setStatus('WRSTOPS gate map position updated in editor. Click Save Gate.');} if(mapClickMode==='newGate'){document.getElementById('newGateMapX').value=p.x.toFixed(4); document.getElementById('newGateMapY').value=p.y.toFixed(4); setStatus('New WRSTOPS gate map position set. Click Create Gate.');} if(mapClickMode==='newPoi'){document.getElementById('newPoiMapX').value=p.x.toFixed(4); document.getElementById('newPoiMapY').value=p.y.toFixed(4); setStatus('New POI map position set. Click Create POI.');} if(mapClickMode==='surveyEditStart'&&selectedKind==='survey'){document.getElementById('editSurveyStartX').value=p.x.toFixed(4); document.getElementById('editSurveyStartY').value=p.y.toFixed(4); setStatus('Survey start updated in editor. Click Save Survey.');} if(mapClickMode==='surveyEditEnd'&&selectedKind==='survey'){document.getElementById('editSurveyEndX').value=p.x.toFixed(4); document.getElementById('editSurveyEndY').value=p.y.toFixed(4); setStatus('Survey end updated in editor. Click Save Survey.');} mapClickMode=null;});
function updateSurveyInfo(){document.getElementById('rsMapInfo').textContent=`Start: ${remoteSurveyStart?remoteSurveyStart.x.toFixed(4)+', '+remoteSurveyStart.y.toFixed(4):'not set'} • End: ${remoteSurveyEnd?remoteSurveyEnd.x.toFixed(4)+', '+remoteSurveyEnd.y.toFixed(4):'not set'}`}
async function init(){events=await api('/events'); const wrap=document.getElementById('eventButtons'); wrap.innerHTML=''; events.forEach(ev=>{const b=document.createElement('button'); b.className='event'; b.innerHTML=`<b>${escapeHtml(ev.name)}</b><span>${escapeHtml(ev.description||'')}</span>`; b.onclick=()=>selectEvent(ev.id); wrap.appendChild(b)}); selectEvent(events[0]?.id||'lib_2026');}
async function selectEvent(id){currentEvent=await api('/events/'+id); document.querySelectorAll('.event').forEach((b,i)=>b.classList.toggle('active',events[i]?.id===id)); document.getElementById('mapTitle').textContent=currentEvent.name+' Map'; const wrap=document.getElementById('mapWrap'); wrap.querySelectorAll('img,.placeholder').forEach(e=>e.remove()); const img=document.createElement('img'); img.src=currentEvent.map_url; img.onerror=()=>{const ph=document.createElement('div'); ph.className='placeholder'; ph.textContent='Map image missing'; wrap.prepend(ph)}; wrap.prepend(img); selectedKind=null; selectedId=null; await refreshAll();}
async function refreshAll(){if(!currentEvent)return; try{[pois,gates,mapAnchors]=await Promise.all([api(`/events/${currentEvent.id}/pois`),api(`/events/${currentEvent.id}/wrstops-gates`),api(`/events/${currentEvent.id}/calibration-anchors`)]); if(dataMode==='survey')surveyPaths=await api(`/events/${currentEvent.id}/survey-paths`); drawBase(); setStatus(`Loaded ${currentEvent.name}: ${pois.length} POIs, ${gates.length} gates, ${mapAnchors.length} anchors.`);}catch(e){setStatus('Refresh failed: '+e.message)}}
function selectPoi(id){setSelected('poi',id); setTab('data', false); dataMode='pois'; renderPois(); drawBase(); setStatus('Selected POI.');}
async function loadPois(){dataMode='pois'; pois=await api(`/events/${currentEvent.id}/pois`); if(selectedKind!=='poi'&&selectedKind!=='newPoi'){setSelected(null,null);} renderPois(); drawBase();}
function renderPois(){const list=document.getElementById('dataList'); const addCard=(selectedKind==='newPoi')?newPoiEditor():''; const poiCards=pois.map(p=>{const sel=selectedKind==='poi'&&selectedId===p.id; return `<div class="card ${sel?'selected':''}" id="poi-${p.id}" onclick="selectPoi('${p.id}')"><h3>${escapeHtml(p.name)}</h3><p>${escapeHtml(p.category)} • map ${n3(p.map_x)}, ${n3(p.map_y)}${p.latitude!=null&&p.longitude!=null?'<br>GPS '+p.latitude+', '+p.longitude:''}</p>${sel?poiEditor(p):''}</div>`}).join(''); list.innerHTML=addCard+(poiCards||'<p class="muted">No POIs.</p>');}
function poiEditor(p){return `<label>Name</label><input id="editPoiName" value="${escapeHtml(p.name)}"><label>Category</label><input id="editPoiCategory" value="${escapeHtml(p.category)}"><div class="row"><div><label>Map X</label><input id="editPoiMapX" value="${n4(p.map_x)}"></div><div><label>Map Y</label><input id="editPoiMapY" value="${n4(p.map_y)}"></div></div><div class="row"><div><label>Latitude</label><input id="editPoiLat" value="${p.latitude??''}"></div><div><label>Longitude</label><input id="editPoiLng" value="${p.longitude??''}"></div></div><div class="row"><button class="primary" onclick="event.stopPropagation(); savePoi('${p.id}')">Save POI</button><button onclick="event.stopPropagation(); mapClickMode='movePoi'; setStatus('Click map to move selected POI.')">Move on Map</button><button onclick="event.stopPropagation(); inferMapFromGps('editPoiLat','editPoiLng','editPoiMapX','editPoiMapY')">Infer Map from GPS</button><button class="danger" onclick="event.stopPropagation(); deletePoi('${p.id}')">Delete</button></div>`}
function startAddPoi(){setSelected('newPoi','new'); setTab('data',false); dataMode='pois'; renderPois(); drawBase(); setStatus('Create a new POI. Enter details or click Place on Map.');}
function newPoiEditor(){return `<div class="card selected"><h3>Add POI</h3><p class="muted">Create a new event POI for ${escapeHtml(currentEvent.name)}.</p><label>Name</label><input id="newPoiName" value="New POI"><label>Category</label><input id="newPoiCategory" value="Custom POIs"><div class="row"><div><label>Map X</label><input id="newPoiMapX" value="0.5000"></div><div><label>Map Y</label><input id="newPoiMapY" value="0.5000"></div></div><div class="row"><div><label>Latitude</label><input id="newPoiLat" placeholder="optional"></div><div><label>Longitude</label><input id="newPoiLng" placeholder="optional"></div></div><div class="row"><button class="primary" onclick="event.stopPropagation(); createPoi()">Create POI</button><button onclick="event.stopPropagation(); mapClickMode='newPoi'; setStatus('Click the map to place the new POI.')">Place on Map</button><button onclick="event.stopPropagation(); inferMapFromGps('newPoiLat','newPoiLng','newPoiMapX','newPoiMapY')">Infer Map from GPS</button><button onclick="event.stopPropagation(); selectedKind=null; selectedId=null; renderPois(); drawBase(); setStatus('Cancelled new POI.')">Cancel</button></div></div>`}
async function createPoi(){const lat=document.getElementById('newPoiLat').value.trim(), lng=document.getElementById('newPoiLng').value.trim(); const payload={name:document.getElementById('newPoiName').value||'New POI',category:document.getElementById('newPoiCategory').value||'Custom POIs',map_x:parseFloat(document.getElementById('newPoiMapX').value),map_y:parseFloat(document.getElementById('newPoiMapY').value),updated_by:'dash_poi_creator'}; if(lat!==''&&lng!==''){payload.latitude=parseFloat(lat); payload.longitude=parseFloat(lng); payload.accuracy_meters=0;} if(!Number.isFinite(payload.map_x)||!Number.isFinite(payload.map_y)){setStatus('Enter valid map X/Y.'); return;} const created=await api(`/events/${currentEvent.id}/pois`,{method:'POST',body:JSON.stringify(payload)}); pois=await api(`/events/${currentEvent.id}/pois`); setSelected('poi',created.id); renderPois(); drawBase(); setStatus('Created POI.');}
async function savePoi(id){const lat=document.getElementById('editPoiLat').value.trim(), lng=document.getElementById('editPoiLng').value.trim(); const payload={name:document.getElementById('editPoiName').value,category:document.getElementById('editPoiCategory').value,map_x:parseFloat(document.getElementById('editPoiMapX').value),map_y:parseFloat(document.getElementById('editPoiMapY').value),updated_by:'dash_editor'}; if(lat!==''&&lng!==''){payload.latitude=parseFloat(lat); payload.longitude=parseFloat(lng); payload.accuracy_meters=0;} await api(`/events/${currentEvent.id}/pois/${id}`,{method:'PUT',body:JSON.stringify(payload)}); pois=await api(`/events/${currentEvent.id}/pois`); setSelected('poi',id); renderPois(); drawBase(); setStatus('Saved POI.');}
async function deletePoi(id){if(!confirm('Delete this POI?'))return; await api(`/events/${currentEvent.id}/pois/${id}`,{method:'DELETE'}); selectedKind=null; selectedId=null; await loadPois(); setStatus('Deleted POI.');}
async function inferMapFromGps(latInputId,lngInputId,mapXInputId,mapYInputId){const lat=parseFloat(document.getElementById(latInputId).value), lng=parseFloat(document.getElementById(lngInputId).value); if(!Number.isFinite(lat)||!Number.isFinite(lng)){setStatus('Enter valid latitude and longitude first.');return} try{const result=await api(`/events/${currentEvent.id}/infer-map-position`,{method:'POST',body:JSON.stringify({latitude:lat,longitude:lng})}); document.getElementById(mapXInputId).value=Number(result.map_x_clamped??result.map_x).toFixed(4); document.getElementById(mapYInputId).value=Number(result.map_y_clamped??result.map_y).toFixed(4); setStatus(`Inferred map position from GPS using ${result.anchor_count} anchors.`);}catch(e){setStatus('Infer map position failed: '+e.message)}}
function selectGate(id){setSelected('gate',id); setTab('data', false); dataMode='gates'; renderGates(); drawBase(); setStatus('Selected WRSTOPS gate.');}
async function loadGates(){dataMode='gates'; gates=await api(`/events/${currentEvent.id}/wrstops-gates`); renderGates(); drawBase();}
function renderGates(){const list=document.getElementById('dataList'); const addCard=(selectedKind==='newGate')?newGateEditor():''; const gateCards=gates.map(g=>{const sel=selectedKind==='gate'&&selectedId===g.id; return `<div class="card ${sel?'selected':''}" id="gate-${g.id}" onclick="selectGate('${g.id}')"><h3>${escapeHtml(g.name)}</h3><p>${escapeHtml(g.connection_status)} • scans ${g.scan_count} • map ${n3(g.map_x)}, ${n3(g.map_y)}${g.latitude!=null&&g.longitude!=null?'<br>GPS '+g.latitude+', '+g.longitude:''}</p>${sel?gateEditor(g):''}</div>`}).join(''); list.innerHTML=addCard+(gateCards||'<p class="muted">No gates.</p>');}
function startAddGate(){setSelected('newGate','new'); setTab('data',false); dataMode='gates'; renderGates(); drawBase(); setStatus('Create a new WRSTOPS gate. Enter details or click Place on Map.');}
function newGateEditor(){return `<div class="card selected"><h3>Add WRSTOPS Gate</h3><p class="muted">Create a new gate for ${escapeHtml(currentEvent.name)}. Use Place on Map, then Create Gate.</p><label>Name</label><input id="newGateName" value="Gate ${gates.length+1}"><div class="row"><div><label>Map X</label><input id="newGateMapX" value="0.5000"></div><div><label>Map Y</label><input id="newGateMapY" value="0.5000"></div></div><div class="row"><div><label>Latitude</label><input id="newGateLat" placeholder="optional"></div><div><label>Longitude</label><input id="newGateLng" placeholder="optional"></div></div><div class="row"><div><label>Scan Count</label><input id="newGateScans" value="0"></div><div><label>IP Address</label><input id="newGateIp" placeholder="optional"></div></div><div class="row"><div><label>Status</label><select id="newGateStatus"><option value="ONLINE">ONLINE</option><option value="OFFLINE">OFFLINE</option></select></div><div><label>Override</label><select id="newGateOverride"><option value="NORMAL">NORMAL</option><option value="OFFLINE">OFFLINE</option></select></div></div><div class="row"><button class="primary" onclick="event.stopPropagation(); createGate()">Create Gate</button><button onclick="event.stopPropagation(); mapClickMode='newGate'; setStatus('Click the map to place the new WRSTOPS gate.')">Place on Map</button><button onclick="event.stopPropagation(); inferMapFromGps('newGateLat','newGateLng','newGateMapX','newGateMapY')">Infer Map from GPS</button><button onclick="event.stopPropagation(); selectedKind=null; selectedId=null; renderGates(); drawBase(); setStatus('Cancelled new gate.')">Cancel</button></div></div>`}
async function createGate(){const lat=document.getElementById('newGateLat').value.trim(), lng=document.getElementById('newGateLng').value.trim(); const payload={name:document.getElementById('newGateName').value||'Gate',map_x:parseFloat(document.getElementById('newGateMapX').value),map_y:parseFloat(document.getElementById('newGateMapY').value),scan_count:parseInt(document.getElementById('newGateScans').value||'0',10),connection_status:document.getElementById('newGateStatus').value,override_status:document.getElementById('newGateOverride').value,ip_address:document.getElementById('newGateIp').value||null,updated_by:'dash_gate_creator'}; if(lat!==''&&lng!==''){payload.latitude=parseFloat(lat); payload.longitude=parseFloat(lng); payload.accuracy_meters=0;} if(!Number.isFinite(payload.map_x)||!Number.isFinite(payload.map_y)){setStatus('Enter valid map X/Y.'); return;} const created=await api(`/events/${currentEvent.id}/wrstops-gates`,{method:'POST',body:JSON.stringify(payload)}); gates=await api(`/events/${currentEvent.id}/wrstops-gates`); setSelected('gate',created.id); renderGates(); drawBase(); setStatus('Created WRSTOPS gate.');}
function gateEditor(g){return `<label>Name</label><input id="editGateName" value="${escapeHtml(g.name)}"><div class="row"><div><label>Map X</label><input id="editGateMapX" value="${n4(g.map_x)}"></div><div><label>Map Y</label><input id="editGateMapY" value="${n4(g.map_y)}"></div></div><div class="row"><div><label>Latitude</label><input id="editGateLat" value="${g.latitude??''}"></div><div><label>Longitude</label><input id="editGateLng" value="${g.longitude??''}"></div></div><div class="row"><div><label>Scan Count</label><input id="editGateScans" value="${g.scan_count??0}"></div><div><label>IP Address</label><input id="editGateIp" value="${escapeHtml(g.ip_address||'')}"></div></div><div class="row"><div><label>Status</label><select id="editGateStatus"><option value="ONLINE" ${g.connection_status==='ONLINE'?'selected':''}>ONLINE</option><option value="OFFLINE" ${g.connection_status==='OFFLINE'?'selected':''}>OFFLINE</option></select></div><div><label>Override</label><select id="editGateOverride"><option value="NORMAL" ${g.override_status==='NORMAL'?'selected':''}>NORMAL</option><option value="OFFLINE" ${g.override_status==='OFFLINE'?'selected':''}>OFFLINE</option></select></div></div><div class="row"><button class="primary" onclick="event.stopPropagation(); saveGate('${g.id}')">Save Gate</button><button onclick="event.stopPropagation(); mapClickMode='moveGate'; setStatus('Click map to move selected WRSTOPS gate.')">Move on Map</button><button onclick="event.stopPropagation(); inferMapFromGps('editGateLat','editGateLng','editGateMapX','editGateMapY')">Infer Map from GPS</button><button class="danger" onclick="event.stopPropagation(); deleteGate('${g.id}')">Delete</button></div>`}
async function saveGate(id){const lat=document.getElementById('editGateLat').value.trim(), lng=document.getElementById('editGateLng').value.trim(); const payload={name:document.getElementById('editGateName').value,map_x:parseFloat(document.getElementById('editGateMapX').value),map_y:parseFloat(document.getElementById('editGateMapY').value),scan_count:parseInt(document.getElementById('editGateScans').value||'0',10),connection_status:document.getElementById('editGateStatus').value,override_status:document.getElementById('editGateOverride').value,ip_address:document.getElementById('editGateIp').value,updated_by:'dash_gate_editor'}; if(lat!==''&&lng!==''){payload.latitude=parseFloat(lat); payload.longitude=parseFloat(lng); payload.accuracy_meters=0;} await api(`/events/${currentEvent.id}/wrstops-gates/${id}`,{method:'PUT',body:JSON.stringify(payload)}); gates=await api(`/events/${currentEvent.id}/wrstops-gates`); setSelected('gate',id); renderGates(); drawBase(); setStatus('Saved WRSTOPS gate.');}
async function deleteGate(id){if(!confirm('Delete this WRSTOPS gate?'))return; await api(`/events/${currentEvent.id}/wrstops-gates/${id}`,{method:'DELETE'}); selectedKind=null; selectedId=null; await loadGates(); setStatus('Deleted WRSTOPS gate.');}
function selectAnchor(id){setSelected('anchor',id); setTab('calibration'); loadAnchors().then(()=>setStatus('Selected calibration anchor.'));}
async function loadAnchors(){mapAnchors=await api(`/events/${currentEvent.id}/calibration-anchors`); document.getElementById('anchorList').innerHTML=mapAnchors.map(a=>`<div class="card ${selectedKind==='anchor'&&selectedId===a.id?'selected':''}" onclick="selectAnchor('${a.id}')"><h3>Anchor</h3><p>map ${n4(a.map_x)}, ${n4(a.map_y)}<br>${a.latitude}, ${a.longitude}</p><button class="danger" onclick="event.stopPropagation(); deleteAnchor('${a.id}')">Delete</button></div>`).join('')||'<p class="muted">No anchors.</p>'; drawBase();}
async function deleteAnchor(id){if(!confirm('Delete this calibration anchor?'))return; await api(`/events/${currentEvent.id}/calibration-anchors/${id}`,{method:'DELETE'}); selectedKind=null; selectedId=null; await loadAnchors(); setStatus('Deleted calibration anchor.');}
async function saveCalibrationAnchor(){if(!calibrationMapPoint){setStatus('Click a map point first.');return} const lat=parseFloat(document.getElementById('calLat').value), lng=parseFloat(document.getElementById('calLng').value); if(!Number.isFinite(lat)||!Number.isFinite(lng)){setStatus('Enter valid latitude and longitude.');return} await api(`/events/${currentEvent.id}/calibration-anchors`,{method:'POST',body:JSON.stringify({map_x:calibrationMapPoint.x,map_y:calibrationMapPoint.y,latitude:lat,longitude:lng,accuracy_meters:0,created_by:'dash_remote'})}); calibrationMapPoint=null; document.getElementById('calMapInfo').textContent='Anchor saved.'; await loadAnchors(); setStatus('Saved remote calibration anchor.');}
function drawSurveyPaths(){const svg=document.getElementById('pathSvg'); surveyPaths.forEach(sp=>{if(sp.start_map_x==null||sp.start_map_y==null)return; marker(sp.start_map_x,sp.start_map_y,'survey',`${sp.id} start`,()=>selectSurveyPath(sp.id)); if(sp.end_map_x!=null&&sp.end_map_y!=null){marker(sp.end_map_x,sp.end_map_y,'survey',`${sp.id} end`,()=>selectSurveyPath(sp.id)); const line=document.createElementNS('http://www.w3.org/2000/svg','line'); line.setAttribute('x1',sp.start_map_x*1000); line.setAttribute('y1',sp.start_map_y*562); line.setAttribute('x2',sp.end_map_x*1000); line.setAttribute('y2',sp.end_map_y*562); line.setAttribute('class','pathSvgLine '+(selectedKind==='survey'&&selectedId===sp.id?'selected':'')); line.style.pointerEvents='auto'; line.onclick=(ev)=>{ev.stopPropagation(); selectSurveyPath(sp.id)}; svg.appendChild(line);}})}
function selectSurveyPath(id){setSelected('survey',id); setTab('data', false); dataMode='survey'; renderSurveyPaths(); drawBase(); setStatus('Selected survey path.');}
async function loadSurveyPaths(){dataMode='survey'; surveyPaths=await api(`/events/${currentEvent.id}/survey-paths`); renderSurveyPaths(); drawBase();}
function renderSurveyPaths(){const list=document.getElementById('dataList'); list.innerHTML=surveyPaths.map(sp=>{const sel=selectedKind==='survey'&&selectedId===sp.id; return `<div class="card ${sel?'selected':''}" onclick="selectSurveyPath('${sp.id}')"><h3>${escapeHtml(sp.name)}</h3><p>${escapeHtml(sp.survey_mode)} • ${escapeHtml(sp.path_type)} • ${sp.point_count} GPS points<br>start ${n3(sp.start_map_x)}, ${n3(sp.start_map_y)} ${sp.end_map_x!=null?'→ end '+n3(sp.end_map_x)+', '+n3(sp.end_map_y):''}</p>${sel?surveyEditor(sp):''}</div>`}).join('')||'<p class="muted">No survey paths.</p>';}
function surveyEditor(sp){return `<label>Name</label><input id="editSurveyName" value="${escapeHtml(sp.name)}"><div class="row"><div><label>Mode</label><select id="editSurveyMode"><option value="direct_path" ${sp.survey_mode==='direct_path'?'selected':''}>Direct Path</option><option value="area_walk" ${sp.survey_mode==='area_walk'?'selected':''}>Area Walk</option></select></div><div><label>Type</label><select id="editSurveyType"><option value="guest" ${sp.path_type==='guest'?'selected':''}>Guest</option><option value="staff" ${sp.path_type==='staff'?'selected':''}>Staff</option><option value="cart" ${sp.path_type==='cart'?'selected':''}>Cart</option><option value="restricted" ${sp.path_type==='restricted'?'selected':''}>Restricted</option><option value="emergency" ${sp.path_type==='emergency'?'selected':''}>Emergency</option></select></div></div><div class="row"><div><label>Start X</label><input id="editSurveyStartX" value="${n4(sp.start_map_x)}"></div><div><label>Start Y</label><input id="editSurveyStartY" value="${n4(sp.start_map_y)}"></div></div><div class="row"><div><label>End X</label><input id="editSurveyEndX" value="${sp.end_map_x??''}"></div><div><label>End Y</label><input id="editSurveyEndY" value="${sp.end_map_y??''}"></div></div><div class="row"><button class="primary" onclick="event.stopPropagation(); saveSurveyPath('${sp.id}')">Save Survey</button><button onclick="event.stopPropagation(); mapClickMode='surveyEditStart'; setStatus('Click map to set survey start.')">Move Start</button><button onclick="event.stopPropagation(); mapClickMode='surveyEditEnd'; setStatus('Click map to set survey end.')">Move End</button><button class="danger" onclick="event.stopPropagation(); deleteSurveyPath('${sp.id}')">Delete</button></div>`}
async function saveSurveyPath(id){const ex=document.getElementById('editSurveyEndX').value.trim(), ey=document.getElementById('editSurveyEndY').value.trim(); const payload={name:document.getElementById('editSurveyName').value,survey_mode:document.getElementById('editSurveyMode').value,path_type:document.getElementById('editSurveyType').value,start_map_x:parseFloat(document.getElementById('editSurveyStartX').value),start_map_y:parseFloat(document.getElementById('editSurveyStartY').value),end_map_x:ex===''?null:parseFloat(ex),end_map_y:ey===''?null:parseFloat(ey),updated_by:'dash_editor'}; await api(`/events/${currentEvent.id}/survey-paths/${id}`,{method:'PUT',body:JSON.stringify(payload)}); await loadSurveyPaths(); setSelected('survey',id); renderSurveyPaths(); drawBase(); setStatus('Saved survey path.');}
async function deleteSurveyPath(id){if(!confirm('Delete this survey path?'))return; await api(`/events/${currentEvent.id}/survey-paths/${id}`,{method:'DELETE'}); selectedKind=null; selectedId=null; await loadSurveyPaths(); setStatus('Deleted survey path.');}
function parseCoords(){const raw=document.getElementById('rsPoints').value.trim(); if(!raw)return[]; return raw.split(/\n+/).map((line,i)=>{const nums=line.match(/-?\d+(?:\.\d+)?/g)||[]; if(nums.length<2)throw new Error(`Line ${i+1} needs lat,lng`); return {seq:i,latitude:parseFloat(nums[0]),longitude:parseFloat(nums[1]),accuracy_meters:0,timestamp:new Date().toISOString()}})}
function previewRemoteSurvey(){drawBase(); const pts=parseCoords(); if(remoteSurveyStart)marker(remoteSurveyStart.x,remoteSurveyStart.y,'survey','Start'); if(remoteSurveyEnd)marker(remoteSurveyEnd.x,remoteSurveyEnd.y,'survey','End'); setStatus(`Preview ready: ${pts.length} GPS points. Save to store this remote survey path.`)}
async function saveRemoteSurvey(){if(!remoteSurveyStart){setStatus('Set a start point on the map first.');return} const mode=document.getElementById('rsMode').value; if(mode==='direct_path'&&!remoteSurveyEnd){setStatus('Direct Path needs an end point.');return} let pts; try{pts=parseCoords()}catch(e){setStatus(e.message);return} if(pts.length<1){setStatus('Paste at least one latitude,longitude point.');return} const payload={name:document.getElementById('rsName').value||'Remote Survey Path',survey_mode:mode,path_type:document.getElementById('rsType').value,start_map_x:remoteSurveyStart.x,start_map_y:remoteSurveyStart.y,end_map_x:remoteSurveyEnd?.x??null,end_map_y:remoteSurveyEnd?.y??null,distance_meters:0,created_by:'dash_remote_survey',points:pts}; const saved=await api(`/events/${currentEvent.id}/survey-paths`,{method:'POST',body:JSON.stringify(payload)}); await loadSurveyPaths(); setSelected('survey',saved.id); setTab('data'); renderSurveyPaths(); drawBase(); setStatus(`Saved remote survey with ${pts.length} GPS points.`)}
async function loadWifiSweeps(){wifiSweeps=await api(`/events/${currentEvent.id}/wifi-sweeps`); const list=document.getElementById('wifiList'); list.innerHTML=wifiSweeps.map(s=>`<div class="card"><h3>${escapeHtml(s.name)}</h3><p>${s.sample_count} samples • ${escapeHtml(s.target_ssid||'All networks')}<br>${escapeHtml(s.created_at||'')}</p><div class="row"><button onclick="viewWifiSweep('${s.id}')">View Heatmap</button><button class="danger" onclick="deleteWifiSweep('${s.id}')">Delete</button></div></div>`).join('')||'<p class="muted">No saved Wi-Fi sweeps yet.</p>';}
async function viewWifiSweep(id){const d=await api(`/events/${currentEvent.id}/wifi-sweeps/${id}`); drawBase(); let drawn=0; (d.samples||[]).forEach(s=>{const x=s.map_x??s.mapX, y=s.map_y??s.mapY; if(x!=null&&y!=null){heat(x,y,s.rssi_dbm,`${s.ssid||''} ${s.rssi_dbm} dBm`); drawn++}}); setStatus(`Viewing ${d.name}: ${drawn}/${(d.samples||[]).length} samples placed on map. Samples without map_x/map_y need calibration at record time.`)}
async function deleteWifiSweep(id){if(!confirm('Delete this Wi-Fi sweep?'))return; await api(`/events/${currentEvent.id}/wifi-sweeps/${id}`,{method:'DELETE'}); await loadWifiSweeps(); drawBase(); setStatus('Deleted Wi-Fi sweep.');}
init().catch(e=>setStatus('Startup failed: '+e.message));
</script>
</body>
</html>
'''




def query_pois_for_event(event_id: str):
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM pois
            WHERE event_id = ?
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
            """,
            (event_id,),
        ).fetchall()
    return [row_to_dict(row) for row in rows]


@app.get("/events/{event_id}/pois")
def get_event_pois(event_id: str):
    return query_pois_for_event(event_id)


@app.get("/events/{event_id}/pois/{poi_id}")
def get_event_poi(event_id: str, poi_id: str):
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM pois WHERE id = ? AND event_id = ?",
            (poi_id, event_id),
        ).fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail="POI not found")

    return row_to_dict(row)


@app.post("/events/{event_id}/pois")
def create_event_poi(event_id: str, payload: PoiCreate):
    poi_id = "custom_" + uuid4().hex[:12]
    timestamp = now_iso()

    gps_source = None
    if payload.latitude is not None and payload.longitude is not None:
        gps_source = "custom_created"

    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO pois (
                id, event_id, name, category, map_x, map_y, is_custom,
                latitude, longitude, accuracy_meters, updated_at, updated_by, gps_source
            )
            VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?)
            """,
            (
                poi_id,
                event_id,
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
            "SELECT * FROM pois WHERE id = ? AND event_id = ?",
            (poi_id, event_id),
        ).fetchone()

    return row_to_dict(row)


@app.put("/events/{event_id}/pois/{poi_id}")
def update_event_poi(event_id: str, poi_id: str, payload: PoiUpdate):
    with get_connection() as conn:
        existing = conn.execute(
            "SELECT * FROM pois WHERE id = ? AND event_id = ?",
            (poi_id, event_id),
        ).fetchone()

        if existing is None:
            raise HTTPException(status_code=404, detail="POI not found")

        name = payload.name if payload.name is not None else existing["name"]
        category = payload.category if payload.category is not None else existing["category"]
        map_x = payload.map_x if payload.map_x is not None else existing["map_x"]
        map_y = payload.map_y if payload.map_y is not None else existing["map_y"]
        latitude = payload.latitude if payload.latitude is not None else existing["latitude"]
        longitude = payload.longitude if payload.longitude is not None else existing["longitude"]
        accuracy_meters = payload.accuracy_meters if payload.accuracy_meters is not None else existing["accuracy_meters"]

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
            WHERE id = ? AND event_id = ?
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
                event_id,
            ),
        )
        conn.commit()

        row = conn.execute(
            "SELECT * FROM pois WHERE id = ? AND event_id = ?",
            (poi_id, event_id),
        ).fetchone()

    return row_to_dict(row)


@app.put("/events/{event_id}/pois/{poi_id}/location")
def update_event_poi_location(event_id: str, poi_id: str, payload: LocationUpdate):
    with get_connection() as conn:
        existing = conn.execute(
            "SELECT * FROM pois WHERE id = ? AND event_id = ?",
            (poi_id, event_id),
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
            WHERE id = ? AND event_id = ?
            """,
            (
                payload.latitude,
                payload.longitude,
                payload.accuracy_meters,
                now_iso(),
                payload.updated_by,
                "manual_location",
                poi_id,
                event_id,
            ),
        )
        conn.commit()

        row = conn.execute(
            "SELECT * FROM pois WHERE id = ? AND event_id = ?",
            (poi_id, event_id),
        ).fetchone()

    return row_to_dict(row)


@app.delete("/events/{event_id}/pois/{poi_id}")
def delete_event_poi(event_id: str, poi_id: str):
    with get_connection() as conn:
        existing = conn.execute(
            "SELECT * FROM pois WHERE id = ? AND event_id = ?",
            (poi_id, event_id),
        ).fetchone()

        if existing is None:
            raise HTTPException(status_code=404, detail="POI not found")

        if not bool(existing["is_custom"]):
            raise HTTPException(status_code=403, detail="Built-in POIs cannot be deleted")

        conn.execute("DELETE FROM pois WHERE id = ? AND event_id = ?", (poi_id, event_id))
        conn.commit()

    return {"deleted": True, "id": poi_id, "event_id": event_id}


@app.get("/pois")
def get_pois():
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM pois
            WHERE event_id = 'lib_2026'
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
            "SELECT * FROM pois WHERE id = ? AND event_id = ?",
            (poi_id, "lib_2026"),
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
                id, event_id, name, category, map_x, map_y, is_custom,
                latitude, longitude, accuracy_meters, updated_at, updated_by, gps_source
            )
            VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?)
            """,
            (
                poi_id,
                payload.event_id or "lib_2026",
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


@app.get("/beacons")
def list_quickfinder_beacons():
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM quickfinder_beacons
            ORDER BY updated_at DESC
            """
        ).fetchall()

    return [beacon_row_to_dict(row) for row in rows]


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


@app.get("/events/{event_id}/wrstops-gates")
def get_wrstops_gates(event_id: str):
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM wrstops_gates
            WHERE event_id = ?
            ORDER BY name COLLATE NOCASE ASC
            """,
            (event_id,),
        ).fetchall()

    return [wrstops_gate_row_to_dict(row) for row in rows]


@app.post("/events/{event_id}/wrstops-gates")
def create_wrstops_gate(event_id: str, payload: WrstopsGateCreate):
    gate_id = "wrstops_" + uuid4().hex[:12]
    timestamp = now_iso()
    name = payload.name.strip() or "Gate"
    scan_count = payload.scan_count if payload.scan_count is not None else 0
    connection_status = (payload.connection_status or "ONLINE").strip().upper() or "ONLINE"
    override_status = (payload.override_status or "NORMAL").strip().upper() or "NORMAL"

    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO wrstops_gates (
                id, event_id, name, map_x, map_y, latitude, longitude, accuracy_meters, scan_count,
                connection_status, ip_address, override_status,
                created_at, updated_at, updated_by
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                gate_id,
                event_id,
                name,
                payload.map_x,
                payload.map_y,
                payload.latitude,
                payload.longitude,
                payload.accuracy_meters,
                scan_count,
                connection_status,
                payload.ip_address,
                override_status,
                timestamp,
                timestamp,
                payload.updated_by,
            ),
        )
        conn.commit()

        row = conn.execute(
            "SELECT * FROM wrstops_gates WHERE id = ? AND event_id = ?",
            (gate_id, event_id),
        ).fetchone()

    return wrstops_gate_row_to_dict(row)


@app.put("/events/{event_id}/wrstops-gates/{gate_id}")
def update_wrstops_gate(event_id: str, gate_id: str, payload: WrstopsGateUpdate):
    with get_connection() as conn:
        existing = conn.execute(
            "SELECT * FROM wrstops_gates WHERE id = ? AND event_id = ?",
            (gate_id, event_id),
        ).fetchone()

        if existing is None:
            raise HTTPException(status_code=404, detail="WRSTOPS gate not found")

        name = payload.name.strip() if payload.name is not None else existing["name"]
        map_x = payload.map_x if payload.map_x is not None else existing["map_x"]
        map_y = payload.map_y if payload.map_y is not None else existing["map_y"]
        latitude = payload.latitude if payload.latitude is not None else existing["latitude"]
        longitude = payload.longitude if payload.longitude is not None else existing["longitude"]
        accuracy_meters = (
            payload.accuracy_meters
            if payload.accuracy_meters is not None
            else existing["accuracy_meters"]
        )
        scan_count = payload.scan_count if payload.scan_count is not None else existing["scan_count"]
        connection_status = (
            payload.connection_status.strip().upper()
            if payload.connection_status is not None
            else existing["connection_status"]
        )
        ip_address = payload.ip_address if payload.ip_address is not None else existing["ip_address"]
        override_status = (
            payload.override_status.strip().upper()
            if payload.override_status is not None
            else existing["override_status"]
        )

        conn.execute(
            """
            UPDATE wrstops_gates
            SET
                name = ?,
                map_x = ?,
                map_y = ?,
                latitude = ?,
                longitude = ?,
                accuracy_meters = ?,
                scan_count = ?,
                connection_status = ?,
                ip_address = ?,
                override_status = ?,
                updated_at = ?,
                updated_by = ?
            WHERE id = ? AND event_id = ?
            """,
            (
                name or existing["name"],
                map_x,
                map_y,
                latitude,
                longitude,
                accuracy_meters,
                scan_count,
                connection_status or "ONLINE",
                ip_address,
                override_status or "NORMAL",
                now_iso(),
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

    return wrstops_gate_row_to_dict(row)


@app.delete("/events/{event_id}/wrstops-gates/{gate_id}")
def delete_wrstops_gate(event_id: str, gate_id: str):
    with get_connection() as conn:
        existing = conn.execute(
            "SELECT * FROM wrstops_gates WHERE id = ? AND event_id = ?",
            (gate_id, event_id),
        ).fetchone()

        if existing is None:
            raise HTTPException(status_code=404, detail="WRSTOPS gate not found")

        conn.execute(
            "DELETE FROM wrstops_gates WHERE id = ? AND event_id = ?",
            (gate_id, event_id),
        )
        conn.commit()

    return {"deleted": True, "id": gate_id, "event_id": event_id}





@app.post("/events/{event_id}/infer-map-position")
def infer_map_position(event_id: str, payload: InferMapPositionRequest):
    """
    Infer normalized map_x/map_y from a known GPS latitude/longitude using
    this event's calibration anchors. Dash uses this for remote POI/gate placement.
    """
    with get_connection() as conn:
        anchor_rows = conn.execute(
            """
            SELECT *
            FROM map_calibration_anchors
            WHERE event_id = ?
              AND latitude IS NOT NULL
              AND longitude IS NOT NULL
              AND map_x IS NOT NULL
              AND map_y IS NOT NULL
            """,
            (event_id,),
        ).fetchall()

    if len(anchor_rows) < payload.min_anchors:
        raise HTTPException(
            status_code=400,
            detail={
                "message": f"Need at least {payload.min_anchors} calibration anchors for this event.",
                "found_anchor_count": len(anchor_rows),
            },
        )

    try:
        transform = fit_affine_transform(anchor_rows)
        map_x, map_y = apply_inverse_affine(transform, payload.latitude, payload.longitude)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {
        "ok": True,
        "event_id": event_id,
        "anchor_count": len(anchor_rows),
        "latitude": payload.latitude,
        "longitude": payload.longitude,
        "map_x": map_x,
        "map_y": map_y,
        "map_x_clamped": max(0.0, min(1.0, map_x)),
        "map_y_clamped": max(0.0, min(1.0, map_y)),
        "transform": transform,
    }
@app.get("/events/{event_id}/calibration-anchors")
def get_calibration_anchors(event_id: str):
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM map_calibration_anchors
            WHERE event_id = ?
            ORDER BY created_at ASC
            """,
            (event_id,),
        ).fetchall()

    return [calibration_anchor_row_to_dict(row) for row in rows]


@app.post("/events/{event_id}/calibration-anchors")
def create_calibration_anchor(event_id: str, payload: CalibrationAnchorCreate):
    anchor_id = "anchor_" + uuid4().hex[:12]
    timestamp = now_iso()

    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO map_calibration_anchors (
                id, event_id, map_x, map_y, latitude, longitude,
                accuracy_meters, created_at, created_by
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                anchor_id,
                event_id,
                payload.map_x,
                payload.map_y,
                payload.latitude,
                payload.longitude,
                payload.accuracy_meters,
                timestamp,
                payload.created_by,
            ),
        )
        conn.commit()

        row = conn.execute(
            "SELECT * FROM map_calibration_anchors WHERE id = ? AND event_id = ?",
            (anchor_id, event_id),
        ).fetchone()

    return calibration_anchor_row_to_dict(row)


@app.delete("/events/{event_id}/calibration-anchors/{anchor_id}")
def delete_calibration_anchor(event_id: str, anchor_id: str):
    with get_connection() as conn:
        existing = conn.execute(
            "SELECT * FROM map_calibration_anchors WHERE id = ? AND event_id = ?",
            (anchor_id, event_id),
        ).fetchone()

        if existing is None:
            raise HTTPException(status_code=404, detail="Calibration anchor not found")

        conn.execute(
            "DELETE FROM map_calibration_anchors WHERE id = ? AND event_id = ?",
            (anchor_id, event_id),
        )
        conn.commit()

    return {"deleted": True, "id": anchor_id}


@app.get("/events/{event_id}/survey-paths")
def get_survey_paths(event_id: str):
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM survey_paths
            WHERE event_id = ?
            ORDER BY created_at DESC
            """,
            (event_id,),
        ).fetchall()

    return [survey_path_row_to_dict(row) for row in rows]


@app.get("/events/{event_id}/survey-paths/{path_id}")
def get_survey_path(event_id: str, path_id: str):
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM survey_paths WHERE id = ? AND event_id = ?",
            (path_id, event_id),
        ).fetchone()

        if row is None:
            raise HTTPException(status_code=404, detail="Survey path not found")

        point_rows = conn.execute(
            """
            SELECT *
            FROM survey_path_points
            WHERE path_id = ?
            ORDER BY seq ASC
            """,
            (path_id,),
        ).fetchall()

    return survey_path_row_to_dict(row, [survey_point_row_to_dict(point) for point in point_rows])


@app.post("/events/{event_id}/survey-paths")
def create_survey_path(event_id: str, payload: SurveyPathCreate):
    path_id = "survey_" + uuid4().hex[:12]
    timestamp = now_iso()
    name = payload.name.strip() or "Survey Path"
    survey_mode = payload.survey_mode.strip().lower() or "direct_path"
    path_type = payload.path_type.strip().lower() or "guest"

    if survey_mode not in {"direct_path", "area_walk"}:
        raise HTTPException(status_code=400, detail="survey_mode must be direct_path or area_walk")

    if path_type not in {"guest", "staff", "cart", "restricted", "emergency"}:
        raise HTTPException(status_code=400, detail="Unsupported path_type")

    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO survey_paths (
                id, event_id, name, survey_mode, path_type,
                start_map_x, start_map_y, end_map_x, end_map_y,
                distance_meters, point_count, created_at, created_by
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                path_id,
                event_id,
                name,
                survey_mode,
                path_type,
                payload.start_map_x,
                payload.start_map_y,
                payload.end_map_x,
                payload.end_map_y,
                payload.distance_meters or 0.0,
                len(payload.points),
                timestamp,
                payload.created_by,
            ),
        )

        for index, point in enumerate(payload.points):
            conn.execute(
                """
                INSERT INTO survey_path_points (
                    id, path_id, seq, latitude, longitude, accuracy_meters, timestamp
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "survey_point_" + uuid4().hex[:12],
                    path_id,
                    point.seq if point.seq is not None else index,
                    point.latitude,
                    point.longitude,
                    point.accuracy_meters,
                    point.timestamp or timestamp,
                ),
            )

        conn.commit()

        row = conn.execute(
            "SELECT * FROM survey_paths WHERE id = ? AND event_id = ?",
            (path_id, event_id),
        ).fetchone()

    return survey_path_row_to_dict(row)


@app.put("/events/{event_id}/survey-paths/{path_id}")
def update_survey_path(event_id: str, path_id: str, payload: SurveyPathUpdate):
    with get_connection() as conn:
        existing = conn.execute(
            "SELECT * FROM survey_paths WHERE id = ? AND event_id = ?",
            (path_id, event_id),
        ).fetchone()

        if existing is None:
            raise HTTPException(status_code=404, detail="Survey path not found")

        name = payload.name.strip() if payload.name is not None else existing["name"]
        survey_mode = payload.survey_mode.strip().lower() if payload.survey_mode is not None else existing["survey_mode"]
        path_type = payload.path_type.strip().lower() if payload.path_type is not None else existing["path_type"]

        if survey_mode not in {"direct_path", "area_walk"}:
            raise HTTPException(status_code=400, detail="survey_mode must be direct_path or area_walk")

        if path_type not in {"guest", "staff", "cart", "restricted", "emergency"}:
            raise HTTPException(status_code=400, detail="Unsupported path_type")

        start_map_x = payload.start_map_x if payload.start_map_x is not None else existing["start_map_x"]
        start_map_y = payload.start_map_y if payload.start_map_y is not None else existing["start_map_y"]
        end_map_x = payload.end_map_x if payload.end_map_x is not None else existing["end_map_x"]
        end_map_y = payload.end_map_y if payload.end_map_y is not None else existing["end_map_y"]
        distance_meters = payload.distance_meters if payload.distance_meters is not None else existing["distance_meters"]

        conn.execute(
            """
            UPDATE survey_paths
            SET
                name = ?,
                survey_mode = ?,
                path_type = ?,
                start_map_x = ?,
                start_map_y = ?,
                end_map_x = ?,
                end_map_y = ?,
                distance_meters = ?
            WHERE id = ? AND event_id = ?
            """,
            (
                name,
                survey_mode,
                path_type,
                start_map_x,
                start_map_y,
                end_map_x,
                end_map_y,
                distance_meters,
                path_id,
                event_id,
            ),
        )
        conn.commit()

        row = conn.execute(
            "SELECT * FROM survey_paths WHERE id = ? AND event_id = ?",
            (path_id, event_id),
        ).fetchone()

    return survey_path_row_to_dict(row)


@app.delete("/events/{event_id}/survey-paths/{path_id}")
def delete_survey_path(event_id: str, path_id: str):
    with get_connection() as conn:
        existing = conn.execute(
            "SELECT * FROM survey_paths WHERE id = ? AND event_id = ?",
            (path_id, event_id),
        ).fetchone()

        if existing is None:
            raise HTTPException(status_code=404, detail="Survey path not found")

        conn.execute("DELETE FROM survey_path_points WHERE path_id = ?", (path_id,))
        conn.execute("DELETE FROM survey_paths WHERE id = ? AND event_id = ?", (path_id, event_id))
        conn.commit()

    return {"deleted": True, "id": path_id}




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



@app.get("/events/{event_id}/wifi-sweeps")
def get_wifi_sweeps(event_id: str):
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM wifi_sweeps
            WHERE event_id = ?
            ORDER BY created_at DESC
            """,
            (event_id,),
        ).fetchall()

    return [wifi_sweep_row_to_dict(row) for row in rows]


@app.get("/events/{event_id}/wifi-sweeps/{sweep_id}")
def get_wifi_sweep(event_id: str, sweep_id: str):
    with get_connection() as conn:
        sweep = conn.execute(
            "SELECT * FROM wifi_sweeps WHERE event_id = ? AND id = ?",
            (event_id, sweep_id),
        ).fetchone()

        if sweep is None:
            raise HTTPException(status_code=404, detail="WiFi sweep not found")

        sample_rows = conn.execute(
            """
            SELECT *
            FROM wifi_sweep_samples
            WHERE sweep_id = ?
            ORDER BY seq ASC
            """,
            (sweep_id,),
        ).fetchall()

    return wifi_sweep_row_to_dict(
        sweep,
        [wifi_sample_row_to_dict(row) for row in sample_rows],
    )


@app.post("/events/{event_id}/wifi-sweeps")
def create_wifi_sweep(event_id: str, payload: WifiSweepCreate):
    sweep_id = "wifi_" + uuid4().hex[:12]
    timestamp = now_iso()
    samples = payload.samples or []

    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO wifi_sweeps (
                id, event_id, name, target_ssid, target_bssid,
                sample_count, created_at, created_by
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                sweep_id,
                event_id,
                payload.name,
                payload.target_ssid,
                payload.target_bssid,
                len(samples),
                timestamp,
                payload.created_by,
            ),
        )

        for point in samples:
            conn.execute(
                """
                INSERT INTO wifi_sweep_samples (
                    id, sweep_id, seq, latitude, longitude, accuracy_meters,
                    map_x, map_y, ssid, bssid, rssi_dbm, frequency_mhz, timestamp
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "wifi_sample_" + uuid4().hex[:12],
                    sweep_id,
                    point.seq,
                    point.latitude,
                    point.longitude,
                    point.accuracy_meters,
                    point.map_x,
                    point.map_y,
                    point.ssid,
                    point.bssid,
                    point.rssi_dbm,
                    point.frequency_mhz,
                    point.timestamp or timestamp,
                ),
            )

        conn.commit()

        row = conn.execute(
            "SELECT * FROM wifi_sweeps WHERE id = ?",
            (sweep_id,),
        ).fetchone()

    return wifi_sweep_row_to_dict(row)


@app.post("/events/{event_id}/wifi-sweeps/{sweep_id}/samples")
def append_wifi_sweep_samples(event_id: str, sweep_id: str, samples: List[WifiSweepSampleCreate]):
    """
    Appends additional samples to an existing Wi-Fi sweep so the Android app can
    resume a saved sweep and continue mapping from where it left off.
    """
    timestamp = now_iso()

    with get_connection() as conn:
        sweep = conn.execute(
            "SELECT * FROM wifi_sweeps WHERE event_id = ? AND id = ?",
            (event_id, sweep_id),
        ).fetchone()

        if sweep is None:
            raise HTTPException(status_code=404, detail="WiFi sweep not found")

        current_max = conn.execute(
            "SELECT COALESCE(MAX(seq), -1) AS max_seq FROM wifi_sweep_samples WHERE sweep_id = ?",
            (sweep_id,),
        ).fetchone()["max_seq"]

        start_seq = int(current_max) + 1

        for offset, point in enumerate(samples or []):
            conn.execute(
                """
                INSERT INTO wifi_sweep_samples (
                    id, sweep_id, seq, latitude, longitude, accuracy_meters,
                    map_x, map_y, ssid, bssid, rssi_dbm, frequency_mhz, timestamp
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "wifi_sample_" + uuid4().hex[:12],
                    sweep_id,
                    start_seq + offset,
                    point.latitude,
                    point.longitude,
                    point.accuracy_meters,
                    point.map_x,
                    point.map_y,
                    point.ssid,
                    point.bssid,
                    point.rssi_dbm,
                    point.frequency_mhz,
                    point.timestamp or timestamp,
                ),
            )

        total_count = conn.execute(
            "SELECT COUNT(*) AS count FROM wifi_sweep_samples WHERE sweep_id = ?",
            (sweep_id,),
        ).fetchone()["count"]

        conn.execute(
            "UPDATE wifi_sweeps SET sample_count = ? WHERE id = ?",
            (total_count, sweep_id),
        )
        conn.commit()

        updated = conn.execute(
            "SELECT * FROM wifi_sweeps WHERE id = ?",
            (sweep_id,),
        ).fetchone()

    return wifi_sweep_row_to_dict(updated)


@app.delete("/events/{event_id}/wifi-sweeps/{sweep_id}")
def delete_wifi_sweep(event_id: str, sweep_id: str):
    with get_connection() as conn:
        existing = conn.execute(
            "SELECT * FROM wifi_sweeps WHERE event_id = ? AND id = ?",
            (event_id, sweep_id),
        ).fetchone()

        if existing is None:
            raise HTTPException(status_code=404, detail="WiFi sweep not found")

        conn.execute("DELETE FROM wifi_sweep_samples WHERE sweep_id = ?", (sweep_id,))
        conn.execute("DELETE FROM wifi_sweeps WHERE id = ?", (sweep_id,))
        conn.commit()

    return {
        "deleted": True,
        "id": sweep_id,
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
