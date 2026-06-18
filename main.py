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

from access_control import enrich_scanner_gate_dict, init_access_control_db, register_access_control

enrich_wrstops_gate_dict = enrich_scanner_gate_dict
from sim_layout import register_sim_layout


DATABASE_PATH = os.getenv("DATABASE_PATH", "beacon.db")
STATIC_DIR = os.getenv("STATIC_DIR", "static")
MAPS_DIR = os.path.join(STATIC_DIR, "maps")

os.makedirs(MAPS_DIR, exist_ok=True)

MAP_EXTENSIONS = [".png", ".jpg", ".jpeg", ".webp"]


def find_map_url(base_name: str) -> str:
    """
    Returns the first existing static map URL for a base filename.

    This lets Dash work with any of these files:
        static/maps/test_fest_map.png
        static/maps/test_fest_map.jpg
        static/maps/test_fest_map.jpeg
        static/maps/test_fest_map.webp

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


app = FastAPI(title="Beacon Server", version="3.7.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


DEFAULT_EVENT_ID = "test_fest"

BUILT_IN_POIS: list[dict] = []


class PoiCreate(BaseModel):
    event_id: Optional[str] = Field(default=DEFAULT_EVENT_ID, max_length=80)
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


class ScannerCreate(BaseModel):
    name: str = Field(default="Scanner", min_length=1, max_length=120)
    device_type: Optional[str] = Field(default="scanner", max_length=40)
    map_x: float = Field(ge=0.0, le=1.0)
    map_y: float = Field(ge=0.0, le=1.0)
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    accuracy_meters: Optional[float] = None
    scan_count: Optional[int] = 0
    connection_status: Optional[str] = Field(default="ONLINE", max_length=40)
    ip_address: Optional[str] = Field(default=None, max_length=80)
    override_status: Optional[str] = Field(default="NORMAL", max_length=40)
    fence_heading_deg: Optional[float] = Field(default=0.0, ge=0.0, lt=360.0)
    portal_flow_flipped: Optional[bool] = Field(default=False)
    updated_by: Optional[str] = "android_siteops"


class ScannerUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    device_type: Optional[str] = Field(default=None, max_length=40)
    map_x: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    map_y: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    accuracy_meters: Optional[float] = None
    scan_count: Optional[int] = None
    connection_status: Optional[str] = Field(default=None, max_length=40)
    ip_address: Optional[str] = Field(default=None, max_length=80)
    override_status: Optional[str] = Field(default=None, max_length=40)
    fence_heading_deg: Optional[float] = Field(default=None, ge=0.0, lt=360.0)
    portal_flow_flipped: Optional[bool] = None
    updated_by: Optional[str] = "android_siteops"


# Legacy aliases for older clients
WrstopsGateCreate = ScannerCreate
WrstopsGateUpdate = ScannerUpdate




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


class DeviceMapSweepCreate(BaseModel):
    name: str = Field(default="Device Sweep", min_length=1, max_length=160)
    map_x: float = Field(ge=0.0, le=1.0)
    map_y: float = Field(ge=0.0, le=1.0)
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    ble_total: int = 0
    ble_strong: int = 0
    ble_medium: int = 0
    ble_weak: int = 0
    wifi_total: int = 0
    wifi_strong: int = 0
    wifi_medium: int = 0
    wifi_weak: int = 0
    created_by: Optional[str] = Field(default="android_device_sweeper", max_length=120)


class InferGpsRequest(BaseModel):
    anchor_ids: Optional[List[str]] = None
    overwrite_existing: bool = False
    min_anchors: int = 3


class InferMapPositionRequest(BaseModel):
    latitude: float
    longitude: float
    min_anchors: int = 3


class InferGpsPositionRequest(BaseModel):
    map_x: float = Field(ge=0.0, le=1.0)
    map_y: float = Field(ge=0.0, le=1.0)
    min_anchors: int = 3


class LiteAuthRequest(BaseModel):
    password: str = Field(default="", max_length=200)


class MessageBoardPostCreate(BaseModel):
    name: str = Field(default="Field Tester", min_length=1, max_length=120)
    subject: str = Field(default="Field Note", min_length=1, max_length=180)
    body: str = Field(default="", min_length=1, max_length=4000)
    source: Optional[str] = Field(default="unknown", max_length=40)


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


def normalize_fence_heading(value: Optional[float]) -> float:
    if value is None:
        return 0.0
    try:
        return float(value) % 360.0
    except (TypeError, ValueError):
        return 0.0


def normalize_portal_flow_flipped(value) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    try:
        return bool(int(value))
    except (TypeError, ValueError):
        return False


def normalize_gate_device_type(value: Optional[str]) -> str:
    raw = (value or "scanner").strip().lower().replace(" ", "_").replace("-", "_")
    aliases = {
        "box": "scanner",
        "reader": "scanner",
        "rfid": "scanner",
        "rfid_reader": "scanner",
        "portal_reader": "scanner",
        "portal": "scanner",
        "phone": "handheld",
        "cellphone": "handheld",
        "mobile": "handheld",
        "tablet": "ipad",
        "i_pad": "ipad",
        "ios_tablet": "ipad",
    }
    raw = aliases.get(raw, raw)
    if raw not in {"scanner", "handheld", "ipad"}:
        raw = "scanner"
    return raw


def public_device_type(value: Optional[str]) -> str:
    return normalize_gate_device_type(value)


def scanner_gate_row_to_dict(row: sqlite3.Row) -> dict:
    device_type = public_device_type(
        row["device_type"] if "device_type" in row.keys() else "scanner"
    )
    return {
        "id": row["id"],
        "event_id": row["event_id"],
        "name": row["name"],
        "device_type": device_type,
        "deviceType": device_type,
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
        "fence_heading_deg": normalize_fence_heading(
            row["fence_heading_deg"] if "fence_heading_deg" in row.keys() else 0.0
        ),
        "fenceHeadingDeg": normalize_fence_heading(
            row["fence_heading_deg"] if "fence_heading_deg" in row.keys() else 0.0
        ),
        "portal_flow_flipped": normalize_portal_flow_flipped(
            row["portal_flow_flipped"] if "portal_flow_flipped" in row.keys() else 0
        ),
        "portalFlowFlipped": normalize_portal_flow_flipped(
            row["portal_flow_flipped"] if "portal_flow_flipped" in row.keys() else 0
        ),
        **enrich_scanner_gate_dict(row),
    }


wrstops_gate_row_to_dict = scanner_gate_row_to_dict


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



def message_board_post_row_to_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "event_id": row["event_id"],
        "name": row["name"],
        "subject": row["subject"],
        "body": row["body"],
        "source": row["source"],
        "created_at": row["created_at"],
    }



def device_map_sweep_row_to_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "event_id": row["event_id"],
        "name": row["name"],
        "map_x": row["map_x"],
        "map_y": row["map_y"],
        "mapX": row["map_x"],
        "mapY": row["map_y"],
        "latitude": row["latitude"],
        "longitude": row["longitude"],
        "ble_total": row["ble_total"],
        "ble_strong": row["ble_strong"],
        "ble_medium": row["ble_medium"],
        "ble_weak": row["ble_weak"],
        "wifi_total": row["wifi_total"],
        "wifi_strong": row["wifi_strong"],
        "wifi_medium": row["wifi_medium"],
        "wifi_weak": row["wifi_weak"],
        "created_at": row["created_at"],
        "created_by": row["created_by"],
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
                event_id TEXT NOT NULL DEFAULT 'test_fest',
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
                device_type TEXT NOT NULL DEFAULT 'portal',
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
        if "device_type" not in existing_gate_columns:
            conn.execute("ALTER TABLE wrstops_gates ADD COLUMN device_type TEXT NOT NULL DEFAULT 'portal'")
        if "fence_heading_deg" not in existing_gate_columns:
            conn.execute("ALTER TABLE wrstops_gates ADD COLUMN fence_heading_deg REAL NOT NULL DEFAULT 0")
        if "portal_flow_flipped" not in existing_gate_columns:
            conn.execute("ALTER TABLE wrstops_gates ADD COLUMN portal_flow_flipped INTEGER NOT NULL DEFAULT 0")


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
            CREATE TABLE IF NOT EXISTS message_board_posts (
                id TEXT PRIMARY KEY,
                event_id TEXT NOT NULL,
                name TEXT NOT NULL,
                subject TEXT NOT NULL,
                body TEXT NOT NULL,
                source TEXT,
                created_at TEXT NOT NULL
            )
            """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_message_board_event_id_created
            ON message_board_posts(event_id, created_at)
            """
        )


        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS device_map_sweeps (
                id TEXT PRIMARY KEY,
                event_id TEXT NOT NULL,
                name TEXT NOT NULL,
                map_x REAL NOT NULL,
                map_y REAL NOT NULL,
                latitude REAL,
                longitude REAL,
                ble_total INTEGER NOT NULL DEFAULT 0,
                ble_strong INTEGER NOT NULL DEFAULT 0,
                ble_medium INTEGER NOT NULL DEFAULT 0,
                ble_weak INTEGER NOT NULL DEFAULT 0,
                wifi_total INTEGER NOT NULL DEFAULT 0,
                wifi_strong INTEGER NOT NULL DEFAULT 0,
                wifi_medium INTEGER NOT NULL DEFAULT 0,
                wifi_weak INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                created_by TEXT
            )
            """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_device_map_sweeps_event_created
            ON device_map_sweeps(event_id, created_at)
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
            conn.execute("ALTER TABLE pois ADD COLUMN event_id TEXT NOT NULL DEFAULT 'test_fest'")

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
                VALUES (?, ?, ?, ?, ?, ?, 0)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    category = excluded.category
                """,
                (
                    poi["id"],
                    DEFAULT_EVENT_ID,
                    poi["name"],
                    poi["category"],
                    poi["map_x"],
                    poi["map_y"],
                ),
            )

        init_access_control_db(conn)

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


register_access_control(app, get_connection, now_iso)


@app.get("/")
def root():
    return {
        "name": "Beacon Server",
        "status": "ok",
        "version": "3.7.0",
        "docs": "/docs",
    }


@app.get("/health")
def health():
    with get_connection() as conn:
        count = conn.execute("SELECT COUNT(*) AS count FROM pois").fetchone()["count"]
        beacon_count = conn.execute("SELECT COUNT(*) AS count FROM quickfinder_beacons").fetchone()["count"]
        scanner_count = conn.execute("SELECT COUNT(*) AS count FROM wrstops_gates").fetchone()["count"]
        wifi_sweep_count = conn.execute("SELECT COUNT(*) AS count FROM wifi_sweeps").fetchone()["count"]

    return {
        "status": "ok",
        "database_path": DATABASE_PATH,
        "poi_count": count,
        "beacon_count": beacon_count,
        "scanner_count": scanner_count,
        "wifi_sweep_count": wifi_sweep_count,
        "maps": [map_file_status(event["map_name"]) for event in EVENTS],
        "time": now_iso(),
    }


EVENTS = [
    {
        "id": "test_fest",
        "name": "Test Fest",
        "map_name": "test_fest_map",
        "description": "Test Fest park map for SiteOps, scanners, and access control.",
    },
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


register_sim_layout(
    app,
    get_connection,
    now_iso,
    get_event_config,
    wrstops_gate_row_to_dict,
    calibration_anchor_row_to_dict,
)


@app.get("/maps/status")
def maps_status():
    return [map_file_status(event["map_name"]) for event in EVENTS]


@app.get("/lite", response_class=HTMLResponse)
def beacon_lite():
    return HTMLResponse(LITE_HTML)


@app.get("/lite-auth-status")
def lite_auth_status():
    # Does not expose the password; just helps confirm Render env is wired.
    configured = bool(os.getenv("BEACON_LITE_PASSWORD"))
    return {"ok": True, "password_configured": configured}


@app.post("/lite-auth")
def lite_auth(payload: LiteAuthRequest):
    expected = os.getenv("BEACON_LITE_PASSWORD", "beacon").strip()
    supplied = (payload.password or "").strip()

    if not expected:
        raise HTTPException(status_code=500, detail="BEACON_LITE_PASSWORD is empty")

    if supplied != expected:
        raise HTTPException(status_code=401, detail="Invalid Beacon Lite password")

    return {"ok": True}


@app.get("/dash", response_class=HTMLResponse)
def dash():
    return HTMLResponse(DASH_HTML)


LITE_HTML = '<!doctype html>\n<html lang="en">\n<head>\n  <meta charset="utf-8" />\n  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />\n  <title>Beacon Lite</title>\n  <style>\n    :root{--bg:#06101b;--panel:#0f1c2b;--line:rgba(255,255,255,.14);--text:#f7fbff;--muted:#9fb3c8;--blue:#64b5f6;--green:#7CFF9B}\n    *{box-sizing:border-box} html,body{height:100%} body{margin:0;background:radial-gradient(circle at top left,#193b5a 0,#06101b 40rem);color:var(--text);font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif;overflow:hidden}\n    button,input,select{font:inherit} button{border:1px solid var(--line);border-radius:12px;background:#1d334f;color:var(--text);padding:10px 12px;cursor:pointer} button.primary{background:#1565c0;border-color:#66bdff} button.good{background:#11613a;border-color:#7CFF9B} button.ghost{background:rgba(255,255,255,.06)} input,select{width:100%;background:#07101b;color:var(--text);border:1px solid var(--line);border-radius:10px;padding:10px;outline:none}.muted{color:var(--muted)}.small{font-size:12px}.hidden{display:none!important}\n    #login{height:100%;display:grid;place-items:center;padding:20px}.loginCard{width:min(420px,100%);background:rgba(15,28,43,.94);border:1px solid var(--line);border-radius:24px;padding:24px;box-shadow:0 20px 60px rgba(0,0,0,.35)}.loginCard h1{margin:0 0 4px;font-size:34px;letter-spacing:.04em}.loginCard p{margin:0 0 18px;color:var(--muted)}\n    #app{height:100%;display:flex;flex-direction:column}.top{display:flex;align-items:center;justify-content:space-between;gap:8px;padding:10px;background:rgba(6,16,27,.92);border-bottom:1px solid var(--line);z-index:5}.brand{font-weight:900;letter-spacing:.04em}.top select{max-width:210px}.topBtns{display:flex;gap:6px;align-items:center}.topBtns button{padding:8px 10px;font-size:13px}\n    .main{flex:1;display:grid;grid-template-columns:1fr 350px;min-height:0}@media(max-width:900px){.main{grid-template-columns:1fr}.side{position:absolute;right:8px;left:8px;bottom:8px;max-height:42vh;z-index:4;border-radius:18px}.side.collapsed{left:auto;width:54px;height:46px;overflow:hidden}.side.collapsed .sideBody,.side.collapsed .tabs{display:none}}\n    .mapWrap{position:relative;overflow:hidden;background:#02070d;touch-action:none}.mapCanvas{position:absolute;inset:0;transform-origin:0 0}.mapImage{position:absolute;object-fit:contain;width:100%;height:100%;opacity:var(--map-opacity,1)}.overlay{position:absolute;inset:0;pointer-events:none}.marker{position:absolute;transform:translate(-50%,-50%);border-radius:999px;border:2px solid #fff;box-shadow:0 2px 8px #000;pointer-events:auto;cursor:pointer}.poi{width:16px;height:16px;background:#e53935}.gate{width:20px;height:20px;background:#111;border-color:#ffd166}.gate::after{content:\'W\';font-size:10px;font-weight:900;color:#ffd166;display:grid;place-items:center;height:100%}.userDot{width:18px;height:18px;background:#43a5ff;box-shadow:0 0 0 10px rgba(67,165,255,.18),0 2px 8px #000}.wifiDot{width:26px;height:26px;border:0;opacity:.68}.pathLine{position:absolute;height:3px;background:#7CFF9B;transform-origin:0 50%;box-shadow:0 0 6px #000}.pathPoint{width:13px;height:13px;background:#7CFF9B;border-color:#001b0b}.zoomCtl{position:absolute;left:8px;bottom:8px;display:flex;gap:6px;z-index:3}.zoomCtl button{width:42px;height:42px;font-weight:900}.legend{position:absolute;left:8px;top:8px;background:rgba(15,28,43,.84);border:1px solid var(--line);border-radius:14px;padding:8px;z-index:3;font-size:12px}.legend div{display:flex;align-items:center;gap:6px;margin:3px 0}.sw{width:12px;height:12px;border-radius:999px;display:inline-block}\n    .side{background:rgba(15,28,43,.95);border-left:1px solid var(--line);min-height:0;display:flex;flex-direction:column}.sideHead{display:flex;align-items:center;justify-content:space-between;gap:8px;padding:10px;border-bottom:1px solid var(--line)}.sideHead h2{margin:0;font-size:17px}.tabs{display:flex;gap:6px;flex-wrap:wrap;padding:8px;border-bottom:1px solid var(--line)}.tabs button{font-size:12px;padding:7px 9px}.tabs button.active{outline:2px solid var(--blue)}.sideBody{overflow:auto;padding:10px}.card{background:rgba(255,255,255,.06);border:1px solid var(--line);border-radius:14px;padding:10px;margin-bottom:8px}.item{padding:9px;border:1px solid var(--line);border-radius:12px;background:rgba(255,255,255,.05);margin-bottom:7px}.item.active{outline:2px solid var(--green);background:rgba(124,255,155,.08)}.item b{display:block}.item span{display:block;color:var(--muted);font-size:12px}.opacityCtl{display:flex;gap:8px;align-items:center;margin-top:8px}.opacityCtl input{padding:0}\n  </style>\n</head>\n<body>\n  <div id="login"><div class="loginCard"><h1>BEACON Lite</h1><p>Private mobile field-test viewer.</p><input id="password" type="password" placeholder="Access password" /><div style="height:10px"></div><button class="primary" id="loginBtn" style="width:100%">Enter</button><p id="loginMsg" class="small muted" style="margin-top:12px"></p></div></div>\n  <div id="app" class="hidden"><div class="top"><div class="brand">BEACON Lite</div><select id="eventSelect"></select><div class="topBtns"><button id="locateBtn">Locate</button><button id="quickBtn">Quick</button><button id="logoutBtn" class="ghost">Exit</button></div></div><div class="main"><div id="mapWrap" class="mapWrap"><div id="mapCanvas" class="mapCanvas"><img id="mapImage" class="mapImage" alt="event map" /><div id="pathLayer" class="overlay"></div><div id="wifiLayer" class="overlay"></div><div id="markerLayer" class="overlay"></div></div><div class="legend"><div><span class="sw" style="background:#43a5ff"></span>You</div><div><span class="sw" style="background:#e53935"></span>POI</div><div><span class="sw" style="background:#ffd166"></span>SiteOps</div><div><span class="sw" style="background:#00d95f"></span>Wi-Fi strong</div><div><span class="sw" style="background:#ff4d4d"></span>Wi-Fi poor</div><div class="opacityCtl"><span>Map</span><input id="mapOpacity" type="range" min="15" max="100" value="100"></div></div><div class="zoomCtl"><button id="zoomOut">−</button><button id="zoomIn">+</button><button id="zoomReset">⤢</button></div></div><div id="side" class="side"><div class="sideHead"><h2 id="sideTitle">Event Data</h2><button id="collapseSide">⌄</button></div><div class="tabs"><button data-tab="pois" class="active">POIs</button><button data-tab="gates">Gates</button><button data-tab="paths">Paths</button><button data-tab="wifi">Wi-Fi</button><button data-tab="quick">Quick</button><button data-tab="messages">Messages</button></div><div id="sideBody" class="sideBody"></div></div></div></div>\n<script>\nconst $=s=>document.querySelector(s);let state={events:[],event:null,pois:[],gates:[],paths:[],sweeps:[],messages:[],selectedTab:\'pois\',selected:null,wifi:null,user:null,scale:1,tx:0,ty:0,dragging:false,last:null};const wrap=$(\'#mapWrap\'),canvas=$(\'#mapCanvas\'),img=$(\'#mapImage\');\nfunction api(path,opts={}){return fetch(path,{headers:{\'Content-Type\':\'application/json\'},...opts}).then(async r=>{if(!r.ok)throw new Error((await r.text()).slice(0,200));return r.json();});}\nfunction wifiColor(r){if(r>=-50)return\'#00d95f\';if(r>=-60)return\'#a8e63f\';if(r>=-67)return\'#ffe45e\';if(r>=-75)return\'#ff9f43\';return\'#ff4d4d\'}\nfunction esc(s){return String(s??\'\').replace(/[&<>\"]/g,c=>({\'&\':\'&amp;\',\'<\':\'&lt;\',\'>\':\'&gt;\',\'\\\"\':\'&quot;\'}[c]||c))}\nfunction showApp(){$(\'#login\').classList.add(\'hidden\');$(\'#app\').classList.remove(\'hidden\');init()} $(\'#loginBtn\').onclick=async()=>{try{await api(\'/lite-auth\',{method:\'POST\',body:JSON.stringify({password:$(\'#password\').value})});localStorage.beaconLiteUnlocked=\'1\';showApp()}catch(e){$(\'#loginMsg\').textContent=\'Wrong password or server error.\'}}; $(\'#password\').addEventListener(\'keydown\',e=>{if(e.key===\'Enter\')$(\'#loginBtn\').click()}); $(\'#logoutBtn\').onclick=()=>{delete localStorage.beaconLiteUnlocked;location.reload()}; if(localStorage.beaconLiteUnlocked===\'1\')showApp();\nasync function init(){const op=localStorage.beaconLiteMapOpacity||100;$(\'#mapOpacity\').value=op;document.documentElement.style.setProperty(\'--map-opacity\',op/100);$(\'#mapOpacity\').oninput=e=>{localStorage.beaconLiteMapOpacity=e.target.value;document.documentElement.style.setProperty(\'--map-opacity\',e.target.value/100)};state.events=await api(\'/events\');const sel=$(\'#eventSelect\');sel.innerHTML=state.events.map(e=>`<option value="${e.id}">${e.name}</option>`).join(\'\');sel.onchange=()=>loadEvent(sel.value);await loadEvent(sel.value||state.events[0].id)}\nasync function loadEvent(id){state.event=state.events.find(e=>e.id===id)||await api(\'/events/\'+id);img.src=state.event.map_url;state.selected=null;$(\'#sideTitle\').textContent=state.event.name;await Promise.all([loadPois(),loadGates(),loadPaths(),loadSweeps()]);renderAll()} async function loadPois(){state.pois=await api(`/events/${state.event.id}/pois`)} async function loadGates(){state.gates=await api(`/events/${state.event.id}/scanners`)} async function loadPaths(){try{state.paths=await api(`/events/${state.event.id}/survey-paths`)}catch(e){state.paths=[]}} async function loadSweeps(){try{state.sweeps=await api(`/events/${state.event.id}/wifi-sweeps`)}catch(e){state.sweeps=[]}}\nfunction mapRect(){const w=wrap.clientWidth,h=wrap.clientHeight,iw=img.naturalWidth||16,ih=img.naturalHeight||9,aspect=iw/ih,box=w/h;let dw,dh,left,top;if(box>aspect){dh=h;dw=h*aspect;left=(w-dw)/2;top=0}else{dw=w;dh=w/aspect;left=0;top=(h-dh)/2}return{left,top,w:dw,h:dh}} function pt(x,y){const r=mapRect();return{left:r.left+x*r.w,top:r.top+y*r.h}} function marker(cls,x,y,title,onClick){const p=pt(x,y),d=document.createElement(\'div\');d.className=\'marker \'+cls;d.style.left=p.left+\'px\';d.style.top=p.top+\'px\';d.title=title||\'\';d.onclick=e=>{e.stopPropagation();onClick&&onClick()};return d}\nfunction renderAll(){renderMarkers();renderPaths();renderWifi();renderSide();applyTransform()} function renderMarkers(){const layer=$(\'#markerLayer\');layer.innerHTML=\'\';state.pois.forEach(p=>layer.appendChild(marker(\'poi\',p.map_x??p.mapX,p.map_y??p.mapY,p.name,()=>select(\'poi\',p.id))));state.gates.forEach(g=>layer.appendChild(marker(\'gate\',g.map_x??g.mapX,g.map_y??g.mapY,g.name,()=>select(\'gate\',g.id))));if(state.user)layer.appendChild(marker(\'userDot\',state.user.x,state.user.y,\'You\'))}\nfunction renderPaths(){const layer=$(\'#pathLayer\');layer.innerHTML=\'\';state.paths.forEach(path=>{const sx=path.start_map_x,sy=path.start_map_y,ex=path.end_map_x,ey=path.end_map_y;layer.appendChild(marker(\'pathPoint\',sx,sy,path.name,()=>select(\'path\',path.id)));if(ex!=null&&ey!=null){layer.appendChild(marker(\'pathPoint\',ex,ey,path.name,()=>select(\'path\',path.id)));const a=pt(sx,sy),b=pt(ex,ey),line=document.createElement(\'div\'),dx=b.left-a.left,dy=b.top-a.top,len=Math.hypot(dx,dy);line.className=\'pathLine\';line.style.left=a.left+\'px\';line.style.top=a.top+\'px\';line.style.width=len+\'px\';line.style.transform=`rotate(${Math.atan2(dy,dx)}rad)`;layer.appendChild(line)}})}\nfunction renderWifi(){const layer=$(\'#wifiLayer\');layer.innerHTML=\'\';if(!state.wifi||!state.wifi.samples)return;state.wifi.samples.forEach(s=>{const x=s.map_x??s.mapX,y=s.map_y??s.mapY;if(x==null||y==null)return;const d=marker(\'wifiDot\',x,y,`${s.ssid||\'\'} ${s.rssi_dbm} dBm`);d.style.background=wifiColor(s.rssi_dbm);layer.appendChild(d)})}\nfunction select(type,id){state.selected={type,id};state.selectedTab=type===\'poi\'?\'pois\':type===\'gate\'?\'gates\':\'paths\';document.querySelectorAll(\'.tabs button\').forEach(b=>b.classList.toggle(\'active\',b.dataset.tab===state.selectedTab));renderSide()} document.querySelectorAll(\'.tabs button\').forEach(b=>b.onclick=()=>{state.selectedTab=b.dataset.tab;state.selected=null;document.querySelectorAll(\'.tabs button\').forEach(x=>x.classList.toggle(\'active\',x===b));renderSide()});\nfunction renderSide(){const body=$(\'#sideBody\'),tab=state.selectedTab;if(tab===\'pois\')body.innerHTML=state.pois.map(p=>`<div class="item ${state.selected?.id===p.id?\'active\':\'\'}" onclick="select(\'poi\',\'${p.id}\')"><b>${p.name}</b><span>${p.category||\'\'} • ${Number(p.map_x??p.mapX).toFixed(3)}, ${Number(p.map_y??p.mapY).toFixed(3)}</span></div>`).join(\'\')||\'<p class="muted">No POIs.</p>\';if(tab===\'gates\')body.innerHTML=state.gates.map(g=>`<div class="item ${state.selected?.id===g.id?\'active\':\'\'}" onclick="select(\'gate\',\'${g.id}\')"><b>${g.name}</b><span>${g.connection_status||\'\'} • scans ${g.scan_count||0}</span></div>`).join(\'\')||\'<p class="muted">No gates.</p>\';if(tab===\'paths\')body.innerHTML=state.paths.map(p=>`<div class="item ${state.selected?.id===p.id?\'active\':\'\'}" onclick="select(\'path\',\'${p.id}\')"><b>${p.name}</b><span>${p.survey_mode} • ${p.path_type} • ${p.point_count||0} pts</span></div>`).join(\'\')||\'<p class="muted">No survey paths.</p>\';if(tab===\'wifi\')body.innerHTML=`<div class="card"><h3>Wi-Fi Heatmap</h3><select id="sweepSel"><option value="">Choose sweep...</option>${state.sweeps.map(s=>`<option value="${s.id}" ${state.wifi?.id===s.id?\'selected\':\'\'}>${s.name} (${s.sample_count||0})</option>`).join(\'\')}</select><div style="height:8px"></div><button class="primary" onclick="loadWifiSweep()">View Sweep</button><button class="ghost" onclick="state.wifi=null;renderWifi()">Clear</button></div>`;if(tab===\'quick\')body.innerHTML=`<div class="card"><h3>Quickfinder</h3><input id="qName" placeholder="My Location"><div style="height:6px"></div><button class="good" onclick="shareMe()">Share My Location</button><div style="height:10px"></div><input id="qCode" placeholder="Enter code"><div style="height:6px"></div><button class="primary" onclick="findCode()">Find Code</button><p id="qMsg" class="small muted"></p></div>`;if(tab===\'messages\'){body.innerHTML=`<div class="card"><h3>Message Board</h3><input id="liteMsgName" placeholder="Your name"><div style="height:6px"></div><input id="liteMsgSubject" placeholder="Subject"><div style="height:6px"></div><textarea id="liteMsgBody" placeholder="Bug report, field note, feature request..." style="width:100%;min-height:95px;background:#07101b;color:#f7fbff;border:1px solid rgba(255,255,255,.14);border-radius:10px;padding:10px;font:inherit"></textarea><div style="height:8px"></div><button class="primary" onclick="postLiteMessage()">Post</button><button class="ghost" onclick="loadLiteMessages()">Refresh</button><p id="liteMsgStatus" class="small muted"></p></div><div id="liteMessageList"></div>`;loadLiteMessages()}}\nasync function loadLiteMessages(){const list=$(\'#liteMessageList\'),status=$(\'#liteMsgStatus\');if(!list||!state.event)return;try{const posts=await api(`/events/${state.event.id}/message-board`);state.messages=posts;list.innerHTML=posts.map(m=>`<div class="item"><b>${esc(m.subject)}</b><span>${esc(m.name)} • ${esc(m.source||\'lite\')} • ${esc(m.created_at||\'\')}</span><div style="margin-top:6px;white-space:pre-wrap">${esc(m.body)}</div></div>`).join(\'\')||\'<p class="muted">No messages yet.</p>\';if(status)status.textContent=`Loaded ${posts.length} messages.`}catch(e){if(status)status.textContent=\'Could not load messages.\'}}\nasync function postLiteMessage(){const status=$(\'#liteMsgStatus\');const name=$(\'#liteMsgName\').value.trim()||\'Lite Tester\';const subject=$(\'#liteMsgSubject\').value.trim();const body=$(\'#liteMsgBody\').value.trim();if(!subject||!body){status.textContent=\'Subject and body required.\';return}try{await api(`/events/${state.event.id}/message-board`,{method:\'POST\',body:JSON.stringify({name,subject,body,source:\'lite\'})});$(\'#liteMsgSubject\').value=\'\';$(\'#liteMsgBody\').value=\'\';status.textContent=\'Posted.\';await loadLiteMessages()}catch(e){status.textContent=\'Post failed.\'}}\nasync function loadWifiSweep(){const id=$(\'#sweepSel\').value;if(!id)return;state.wifi=await api(`/events/${state.event.id}/wifi-sweeps/${id}`);renderWifi()} async function locate(){if(!navigator.geolocation){alert(\'GPS not available\');return}navigator.geolocation.getCurrentPosition(async pos=>{try{const res=await api(`/events/${state.event.id}/infer-map-position`,{method:\'POST\',body:JSON.stringify({latitude:pos.coords.latitude,longitude:pos.coords.longitude})});state.user={x:res.map_x_clamped??res.map_x,y:res.map_y_clamped??res.map_y};renderMarkers()}catch(e){alert(\'GPS found, but map needs 3 calibration anchors to place you.\\n\'+pos.coords.latitude+\', \'+pos.coords.longitude)}},err=>alert(err.message),{enableHighAccuracy:true,timeout:12000})} $(\'#locateBtn\').onclick=locate;$(\'#quickBtn\').onclick=()=>{state.selectedTab=\'quick\';document.querySelectorAll(\'.tabs button\').forEach(b=>b.classList.toggle(\'active\',b.dataset.tab===\'quick\'));renderSide()};\nasync function shareMe(){const msg=$(\'#qMsg\');navigator.geolocation.getCurrentPosition(async pos=>{try{const res=await api(\'/beacons\',{method:\'POST\',body:JSON.stringify({name:$(\'#qName\').value||\'Shared Location\',latitude:pos.coords.latitude,longitude:pos.coords.longitude,accuracy_meters:pos.coords.accuracy,updated_by:\'beacon_lite\'})});msg.textContent=\'Code: \'+res.code}catch(e){msg.textContent=\'Share failed.\'}},e=>msg.textContent=e.message,{enableHighAccuracy:true,timeout:12000})} async function findCode(){const msg=$(\'#qMsg\');try{const res=await api(\'/beacons/\'+$(\'#qCode\').value.trim().toUpperCase());msg.textContent=`${res.name}: ${res.latitude.toFixed(6)}, ${res.longitude.toFixed(6)}`}catch(e){msg.textContent=\'Code not found.\'}}\nfunction applyTransform(){canvas.style.transform=`translate(${state.tx}px,${state.ty}px) scale(${state.scale})`} $(\'#zoomIn\').onclick=()=>{state.scale=Math.min(5,state.scale*1.25);applyTransform()};$(\'#zoomOut\').onclick=()=>{state.scale=Math.max(.7,state.scale/1.25);applyTransform()};$(\'#zoomReset\').onclick=()=>{state.scale=1;state.tx=0;state.ty=0;applyTransform()};wrap.addEventListener(\'pointerdown\',e=>{state.dragging=true;state.last={x:e.clientX,y:e.clientY};wrap.setPointerCapture(e.pointerId)});wrap.addEventListener(\'pointermove\',e=>{if(!state.dragging)return;state.tx+=e.clientX-state.last.x;state.ty+=e.clientY-state.last.y;state.last={x:e.clientX,y:e.clientY};applyTransform()});wrap.addEventListener(\'pointerup\',()=>state.dragging=false);wrap.addEventListener(\'pointercancel\',()=>state.dragging=false);$(\'#collapseSide\').onclick=()=>{$(\'#side\').classList.toggle(\'collapsed\');$(\'#collapseSide\').textContent=$(\'#side\').classList.contains(\'collapsed\')?\'⌃\':\'⌄\'};window.addEventListener(\'resize\',renderAll);img.onload=renderAll;\n</script></body></html>'

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
    .layout{display:grid;grid-template-columns:minmax(420px,1.15fr) minmax(360px,.85fr);gap:16px}@media(max-width:980px){.layout{grid-template-columns:1fr}}.dashShell{display:grid;grid-template-columns:minmax(240px,260px) minmax(0,1fr);gap:16px;align-items:start}@media(max-width:1100px){.dashShell{grid-template-columns:1fr}}.dashMain{min-width:0}.dashSidebar{position:sticky;top:18px;min-width:240px}.dashSidebar .panelBody{overflow:visible}.dashLayerList{display:flex;flex-direction:column;gap:6px}.dashLayerItem{display:flex;align-items:center;gap:10px;font-size:13px;line-height:1.3;padding:8px 12px;border-radius:10px;border:1px solid var(--line);background:rgba(255,255,255,.04);cursor:pointer;color:#d8edf8;white-space:nowrap}.dashLayerItem input[type=checkbox]{width:18px;height:18px;min-width:18px;max-width:18px;padding:0;margin:0;flex:0 0 18px;accent-color:var(--green)}.accessPortalOrient{margin-top:12px;padding-top:12px;border-top:1px solid var(--line)}.accessPortalOrient h4{margin:0 0 6px;font-size:14px;color:#b3e5fc}.accessPortalOrient input[type=range]{padding:0;margin:6px 0;width:100%}.accessPortalOrientDeg{color:#64b5f6;font-weight:700}.flowFlipBtn{width:100%;margin:4px 0 8px;text-align:center;font-size:13px}.flowFlipBtn.active{outline:2px solid #ffb74d;background:#3d2e14;border-color:#ffb74d}.accessScannerScale{margin-top:12px;padding-top:12px;border-top:1px solid var(--line)}.accessScannerScale label{display:flex;justify-content:space-between;align-items:center;margin:0 0 6px;font-size:12px;color:var(--muted)}.accessScannerScale input[type=range]{padding:0;width:100%}.gateFenceLine{stroke:#64b5f6;stroke-width:2.5;stroke-linecap:round;opacity:.9;pointer-events:none}.gateSnapSvgDot{fill:#64b5f6;stroke:#fff;stroke-width:1.2;pointer-events:none}.gateSnapSvgDot.selected{fill:#6df7a7}
    .panel{background:rgba(16,28,43,.94);border:1px solid var(--line);border-radius:18px;box-shadow:0 14px 32px rgba(0,0,0,.28);overflow:hidden}.panelHeader{padding:13px 15px;border-bottom:1px solid var(--line);display:flex;justify-content:space-between;gap:10px;align-items:center}.panelHeader h2{margin:0;font-size:18px}.panelBody{padding:14px}.muted{color:var(--muted);font-size:12px}.status{color:#b7d7ff;font-size:12px;margin-top:8px;white-space:pre-wrap}.row{display:flex;gap:8px;align-items:center;flex-wrap:wrap}.row>*{flex:1}.list{display:flex;flex-direction:column;gap:8px;max-height:520px;overflow:auto}.card{background:var(--panel2);border:1px solid var(--line);border-radius:14px;padding:10px}.card.selected{outline:2px solid var(--green);background:#173a35}.card h3{margin:0 0 4px;font-size:15px}.card p{margin:0 0 8px;color:var(--muted);font-size:12px}.small{font-size:11px;color:var(--muted)}
    .mapWrap{position:relative;width:100%;aspect-ratio:16/9;background:#0d1724;border-radius:14px;overflow:hidden;border:1px solid var(--line)}.mapStage{position:absolute;inset:0;transform-origin:0 0;will-change:transform}.mapWrap img{position:absolute;inset:0;width:100%;height:100%;object-fit:contain}.placeholder{position:absolute;inset:0;background:linear-gradient(135deg,#29475e,#17482a);display:flex;align-items:center;justify-content:center;color:#d8edf8}.marker{position:absolute;transform:translate(-50%,-50%);border-radius:50%;border:2px solid #fff;box-shadow:0 1px 8px rgba(0,0,0,.5);cursor:pointer}.marker.gate{overflow:visible;border-radius:4px;transform:translate(-50%,-50%) scale(var(--dash-scanner-scale,0.72))}.gateSnapDot{position:absolute;width:4px;height:4px;border-radius:50%;background:#64b5f6;border:1px solid #fff;transform:translate(-50%,-50%);pointer-events:auto;box-shadow:0 0 2px rgba(0,0,0,.65);z-index:2}.gateSnapDot.selected{background:#6df7a7}.gateSnapDotHit{width:12px;height:12px;background:transparent;border:0;box-shadow:none}.mapPanLockBtn{position:absolute;top:10px;right:10px;z-index:12;width:36px;height:36px;padding:0;border-radius:10px;background:rgba(8,17,27,.9);border:1px solid var(--line);font-size:17px;line-height:1;cursor:pointer;box-shadow:0 4px 14px rgba(0,0,0,.35)}.mapPanLockBtn.unlocked{background:rgba(21,58,90,.92)}.mapWrap.mapPanLocked{cursor:default}.gateDragHandle{position:absolute;left:calc(50% + 8px);top:calc(50% + 8px);width:11px;height:11px;border-radius:50%;background:#ffe082;border:2px solid #fff;transform:translate(-50%,-50%);cursor:grab;pointer-events:auto;z-index:4;box-shadow:0 1px 6px rgba(0,0,0,.45)}.gateDragHandle.dragging{cursor:grabbing;background:#6df7a7}.marker.gate.draggingGate{opacity:.88}.gateSnapDotHit::after{content:'';position:absolute;left:50%;top:50%;width:4px;height:4px;transform:translate(-50%,-50%);border-radius:50%;background:#64b5f6;border:1px solid #fff;box-shadow:0 0 2px rgba(0,0,0,.65);pointer-events:none}.marker.selected{outline:3px solid var(--green);outline-offset:3px}.poi{width:16px;height:16px;background:#e53935}.gate{width:16px;height:9px;background:#9c27b0;color:#fff;display:grid;place-items:center;font-size:8px;font-weight:900;border-radius:3px}.gate::after{content:'S'}.gate.handheld{width:12px;height:18px;border-radius:4px;background:#1565c0;font-size:7px}.gate.handheld::after{content:'H'}.gate.ipad{width:17px;height:13px;border-radius:4px;background:#00a884;font-size:7px}.gate.ipad::after{content:'I'}.gate.scanner,.gate.portal{width:18px;height:10px;border-radius:3px;background:#9c27b0}.gate.scanner::after,.gate.portal::after{content:'S'}.marker.simLoc{width:14px;height:14px;border-radius:4px;font-size:8px;font-weight:900;display:grid;place-items:center;color:#fff}.marker.simLoc.vendor{background:#ff9800}.marker.simLoc.staff{background:#42a5f5}.marker.simLoc::after{content:attr(data-sim-loc-icon)}.marker.simLoc.selected{outline:2px solid #ffe082}.anchor{width:14px;height:14px;background:#00e5ff}.survey{width:18px;height:18px;background:#ffd166}.heat{width:30px;height:30px;border:0;opacity:.62;mix-blend-mode:screen}.deviceBlob{position:absolute;transform:translate(-50%,-50%);border-radius:999px;pointer-events:auto;cursor:pointer;mix-blend-mode:screen;filter:blur(.2px);box-shadow:0 0 22px rgba(255,255,255,.08)}.deviceBlob.selected{outline:2px solid rgba(255,255,255,.9);outline-offset:4px;box-shadow:0 0 0 5px rgba(124,255,155,.18),0 0 30px rgba(124,255,155,.35)}.deviceBlobLabel{position:absolute;transform:translate(-50%,-50%);font-weight:900;color:#f7fbff;font-size:12px;text-shadow:0 2px 6px #000,0 0 4px #000;pointer-events:none;background:rgba(0,0,0,.34);border:1px solid rgba(255,255,255,.22);border-radius:999px;padding:2px 6px;line-height:1}.deviceBlobCard{position:absolute;transform:translate(-50%,0);background:rgba(6,16,27,.94);border:1px solid rgba(255,255,255,.2);border-radius:12px;padding:7px 9px;color:#f5f8fc;font-size:11px;white-space:nowrap;pointer-events:auto;cursor:pointer;box-shadow:0 8px 22px rgba(0,0,0,.45)}.deviceBlobCard.selected{border-color:#7CFF9B;box-shadow:0 0 0 2px rgba(124,255,155,.25),0 8px 22px rgba(0,0,0,.45)}.deviceBlobCard b{display:block;font-size:12px;margin-bottom:2px}.deviceSweepStat{font-variant-numeric:tabular-nums;color:#d8edf8}.deviceSweepModePill{display:inline-block;border:1px solid var(--line);border-radius:999px;padding:2px 7px;margin-left:6px;font-size:10px;color:var(--muted)}.pathLine{position:absolute;left:0;top:0;width:100%;height:100%;pointer-events:none}.legend{display:flex;align-items:center;gap:8px;font-size:11px;color:var(--muted);margin-top:8px}.grad{width:160px;height:14px;border-radius:10px;background:linear-gradient(90deg,#00e676,#9cff57,#ffeb3b,#ff9800,#ff1744)}
    .pathSvgLine{stroke:#ffd166;stroke-width:5;stroke-linecap:round;fill:none;opacity:.78}.pathSvgLine.selected{stroke:#6df7a7;stroke-width:8;opacity:1}.zoneColorSwatch{width:28px;height:28px;border-radius:8px;border:2px solid rgba(255,255,255,.45);cursor:pointer;box-shadow:0 2px 8px rgba(0,0,0,.35)}.zoneColorSwatch.active{outline:2px solid var(--green);outline-offset:2px}.zoneColorPreview{width:44px;height:44px;border-radius:12px;border:1px solid rgba(255,255,255,.35);box-shadow:inset 0 0 0 1px rgba(0,0,0,.25)}.mapControls{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-top:10px;padding:8px 10px;border:1px solid var(--line);border-radius:12px;background:rgba(7,16,27,.72)}.mapControlGroup{display:flex;align-items:center;gap:10px;flex:1;min-width:min(100%,220px)}.mapControls label{margin:0;color:var(--muted);font-size:12px;white-space:nowrap}.mapControls input[type=range]{padding:0;flex:1;min-width:80px}.mapOpacityValue{min-width:42px;text-align:right;color:#b7d7ff;font-size:12px}.gateSection{margin:8px 0;border:1px solid var(--line);border-radius:12px;background:rgba(255,255,255,.03);overflow:hidden}.gateSection summary{cursor:pointer;padding:10px 12px;font-size:13px;font-weight:600;color:#b3e5fc;list-style:none;display:flex;align-items:center;justify-content:space-between}.gateSection summary::-webkit-details-marker{display:none}.gateSection summary::after{content:'▾';color:var(--muted);transition:transform .15s ease}.gateSection[open] summary::after{transform:rotate(180deg)}.gateSectionBody{padding:0 12px 12px}.dashSearch{display:grid;grid-template-columns:minmax(240px,1fr) auto auto;gap:8px;align-items:start;margin:0 0 14px}.dashSearch input{height:42px}.searchResults{grid-column:1/-1;display:flex;gap:6px;flex-wrap:wrap}.searchChip{border:1px solid var(--line);border-radius:999px;background:rgba(255,255,255,.06);padding:5px 9px;font-size:12px;cursor:pointer}.searchChip.active{outline:2px solid var(--green);background:rgba(124,255,155,.12)}.marker.searchHit{animation:beaconPulse 1.1s ease-in-out infinite;outline:4px solid var(--green);outline-offset:5px;z-index:40}@keyframes beaconPulse{0%,100%{box-shadow:0 0 0 0 rgba(124,255,155,.65),0 1px 8px rgba(0,0,0,.5)}50%{box-shadow:0 0 0 12px rgba(124,255,155,0),0 1px 8px rgba(0,0,0,.5)}}.hidden{display:none!important}
  </style>
</head>
<body>
<div class="app">
  <div class="top"><div class="brand"><h1>Beacon Dash</h1><p>Event admin, Wi-Fi heatmaps, and remote surveying.</p></div><div class="events" id="eventButtons"></div></div>
  <div class="tabs" id="tabs"><button class="tab active" data-tab="overview">Overview</button><button class="tab" data-tab="wifi">Wi-Fi Heatmaps</button><button class="tab" data-tab="deviceSweeps">Device Sweeps</button><button class="tab" data-tab="remoteSurvey">Remote Survey</button><button class="tab" data-tab="calibration">Calibration</button><button class="tab" data-tab="access">Access Control</button><button class="tab" data-tab="data">POIs / Survey</button><button class="tab" data-tab="messages">Messages</button></div><br />
  <div class="dashShell">
  <aside class="panel dashSidebar"><div class="panelHeader"><h2>Map Layers</h2></div><div class="panelBody"><div class="dashLayerList"><label class="dashLayerItem"><input type="checkbox" id="accessLayerSnap" checked> Barrier snaps</label><label class="dashLayerItem"><input type="checkbox" id="accessLayerBarriers" checked> Barriers</label><label class="dashLayerItem"><input type="checkbox" id="accessLayerZones" checked> Zones</label><label class="dashLayerItem"><input type="checkbox" id="accessLayerGates" checked> Scanners</label><label class="dashLayerItem"><input type="checkbox" id="accessLayerPois" checked> POIs</label><label class="dashLayerItem"><input type="checkbox" id="accessLayerAnchors" checked> Anchors</label><label class="dashLayerItem"><input type="checkbox" id="accessLayerWorkLocs" checked> Work locations</label><label class="dashLayerItem"><input type="checkbox" id="accessLayerTileGrid" checked> Tile grid (2ft, 400×225)</label><label class="dashLayerItem"><input type="checkbox" id="accessLayerQueues" checked> Queue lines</label></div><div class="accessScannerScale"><label>Scanner size <span id="dashScannerScaleValue">72%</span></label><input id="dashScannerScale" type="range" min="50" max="130" value="72"></div><div id="accessPortalOrient" class="accessPortalOrient hidden"><h4 id="accessPortalOrientTitle">Fence heading</h4><p class="small">Drag to align snap points with the fence line.</p><label>Heading <span class="accessPortalOrientDeg" id="accessPortalOrientDeg">0°</span></label><input id="mapPortalFenceHeading" type="range" min="0" max="359" value="0"><label style="margin-top:10px">Walk-through</label><p class="small">Arrow shows foot-traffic direction (⊥ fence).</p><button type="button" id="portalFlowFlipBtn" class="flowFlipBtn" onclick="togglePortalFlowFlip()" title="Reverse walk-through direction">⇄ Flip direction</button><div class="row" style="margin-top:6px"><button class="primary" onclick="savePortalFenceHeading()">Save</button><button onclick="resetPortalFenceHeadingPreview()">Reset</button></div></div></div></aside>
  <div class="dashMain">
  <div class="dashSearch"><input id="dashSearchInput" placeholder="Search scanners, POIs, survey paths, anchors, device sweeps..." onkeydown="if(event.key==='Enter')dashSearch()" oninput="if(!this.value.trim())clearDashSearch()"><button class="primary" onclick="dashSearch()">Search</button><button class="ghost" onclick="clearDashSearch()">Clear</button><div id="dashSearchResults" class="searchResults"></div></div>
  <div class="layout">
    <div class="panel"><div class="panelHeader"><h2 id="mapTitle">Map</h2><button onclick="refreshAll()">Refresh</button></div><div class="panelBody"><div class="mapWrap" id="mapWrap"><button type="button" class="mapPanLockBtn" id="mapPanLockBtn" onclick="toggleMapPanLock()" title="Lock map pan (prevents edge scrolling)">&#128274;</button><div class="mapStage" id="mapStage"><div class="placeholder">Map loading...</div><svg class="pathLine" id="pathSvg" viewBox="0 0 1000 562" preserveAspectRatio="none"></svg></div></div><div class="mapControls"><div class="mapControlGroup"><label for="mapOpacity">Map opacity</label><input id="mapOpacity" type="range" min="15" max="100" value="100" oninput="setMapOpacity(this.value)"><span class="mapOpacityValue" id="mapOpacityValue">100%</span></div><div class="mapControlGroup"><label for="mapZoom">Map zoom</label><input id="mapZoom" type="range" min="100" max="300" value="100" oninput="setMapZoom(this.value)"><span class="mapOpacityValue" id="mapZoomValue">100%</span><button type="button" class="ghost" onclick="resetMapView()" title="Reset pan and zoom">Reset view</button></div></div><div class="legend"><div class="grad"></div><span>Wi-Fi signal: green strongest → red weakest</span></div><div class="status" id="status">Ready.</div></div></div>
    <div class="panel"><div class="panelHeader"><h2 id="toolTitle">Overview</h2></div><div class="panelBody">
      <section id="tab-overview"><p class="muted">Click a POI, calibration anchor, or survey path directly on the map to select it. The matching item highlights in the list on the right and expands with edit/delete controls.</p><div class="card"><h3>Selection behavior</h3><p>POIs and survey paths are now linked both ways: map → list and list → map.</p></div></section>
      <section id="tab-wifi" class="hidden"><div class="row"><button onclick="loadWifiSweeps()">Refresh Sweeps</button><button class="ghost" onclick="clearOverlay(); drawBase();">Clear Layer</button></div><br /><div class="list" id="wifiList"></div></section>
      <section id="tab-deviceSweeps" class="hidden"><p class="muted">Device Sweep blobs are saved from the Android map-side Device Sweeper. Select a saved sweep to inspect it, or view all as a cleaner overlay.</p><div class="row"><button onclick="loadDeviceSweeps()">Refresh</button><button id="dsBleBtn" onclick="setDeviceSweepMode('BLE')">BLE</button><button id="dsWifiBtn" onclick="setDeviceSweepMode('WIFI')">Wi-Fi</button><button id="dsReadableBtn" onclick="setDeviceSweepView('readable')">Readable</button><button id="dsRangeBtn" onclick="setDeviceSweepView('range')">Range</button><button onclick="viewAllDeviceSweeps()">View All</button><button class="ghost" onclick="selectedDeviceSweepId=null; deviceSweepShowAll=false; renderDeviceSweepList(); drawDeviceSweeps();">Hide Blobs</button></div><br /><div class="list" id="deviceSweepList"></div></section>
      <section id="tab-remoteSurvey" class="hidden"><label>Survey name</label><input id="rsName" placeholder="North Gate to Box Office" /><div class="row"><div><label>Mode</label><select id="rsMode"><option value="direct_path">Direct Path</option><option value="area_walk">Area Walk</option></select></div><div><label>Path Type</label><select id="rsType"><option value="guest">Guest</option><option value="staff">Staff</option><option value="cart">Cart</option><option value="restricted">Restricted</option><option value="emergency">Emergency</option></select></div></div><div class="row"><button onclick="mapClickMode='surveyStart'; setStatus('Click map for survey start point.')">Set Start on Map</button><button onclick="mapClickMode='surveyEnd'; setStatus('Click map for survey destination/end point.')">Set End on Map</button></div><div class="small" id="rsMapInfo">Start/end map anchors not set.</div><label>GPS coordinates from Google Maps</label><textarea id="rsPoints" placeholder="38.896889, -77.036583\n38.896700, -77.036200\n38.896500, -77.035900"></textarea><div class="row"><button class="primary" onclick="saveRemoteSurvey()">Save Survey Path</button><button onclick="previewRemoteSurvey()">Preview</button></div></section>
      <section id="tab-calibration" class="hidden"><p class="muted">Remote calibration lets you click a known map point, paste its latitude/longitude from Google Maps, and save it as a calibration anchor.</p><div class="row"><button onclick="mapClickMode='calibration'; setStatus('Click map where this GPS coordinate belongs.')">Set Map Point</button><button onclick="loadAnchors()">Refresh Anchors</button><button onclick="inferCalibrationGpsFromMap()">Infer GPS from Selected Map Point</button></div><div class="small" id="calMapInfo">No map point selected.</div><label>Latitude</label><input id="calLat" placeholder="38.896889" /><label>Longitude</label><input id="calLng" placeholder="-77.036583" /><div class="row"><button class="primary" onclick="saveCalibrationAnchor()">Save Anchor</button></div><br /><div class="list" id="anchorList"></div></section><section id="tab-messages" class="hidden"><p class="muted">Field-test message board. Use this for bug reports, feature requests, notes, or test feedback.</p><div class="card"><label>Name</label><input id="msgName" placeholder="Your name" /><label>Subject</label><input id="msgSubject" placeholder="Bug, idea, question..." /><label>Body</label><textarea id="msgBody" placeholder="What happened? What should change?" style="width:100%;min-height:120px;background:#0d1520;color:#f7fbff;border:1px solid rgba(255,255,255,.18);border-radius:10px;padding:10px;"></textarea><div class="row"><button class="primary" onclick="postMessageBoard()">Post Message</button><button onclick="loadMessageBoard()">Refresh</button></div></div><div class="list" id="messageList"></div></section>
      <section id="tab-data" class="hidden"><div class="row"><button onclick="loadPois()">POIs</button><button onclick="loadSurveyPaths()">Survey Paths</button><button class="primary" onclick="startAddPoi()">+ POI</button></div><br /><div id="dataList" class="list"></div></section>
      <section id="tab-access" class="hidden">
        <p class="muted">Place scanners, draw fences, flood-fill zones, then set access rules.</p>
        <div class="row">
          <button data-access-tool="select" class="primary" onclick="setAccessTool('select')">Select</button>
          <button data-access-tool="drawBarrier" onclick="setAccessTool('drawBarrier')">Draw Barrier</button>
          <button data-access-tool="drawQueue" onclick="setAccessTool('drawQueue')">Draw Queue</button>
          <button data-access-tool="fillZone" onclick="setAccessTool('fillZone')">Fill Zone</button>
          <button data-access-tool="linkPortal" onclick="setAccessTool('linkPortal')">Access Rules</button>
          <button data-access-tool="rfidDevices" onclick="setAccessTool('rfidDevices')">Scanners</button><button data-access-tool="workLocations" onclick="setAccessTool('workLocations')">Work Locations</button>
        </div>
        <div id="accessRfidSection" class="hidden">
        <h3 style="margin:14px 0 6px">Scanners</h3>
        <div class="row"><button class="primary" onclick="startAddGate()">+ Scanner</button><button onclick="loadGates()">Refresh</button></div>
        <div class="list" id="accessRfidList" style="margin-top:8px"></div>
        </div>
        <div class="row" style="margin-top:10px">
          <div><label>Barrier name</label><input id="accessBarrierName" placeholder="North fence" /></div>
          <div><label>Barrier type</label><select id="accessBarrierType"><option value="fence">Fence</option><option value="barricade">Barricade</option><option value="wall">Wall</option><option value="rope">Rope</option></select></div>
        </div>
        <div class="row" style="margin-top:8px">
          <button class="primary" onclick="finishDraftBarrier()">Finish Barrier</button>
          <button onclick="closeDraftBarrier()">Close Perimeter</button>
          <button onclick="cancelDraftBarrier()">Cancel Draw</button>
        </div>
        <div id="accessQueueSection" class="hidden" style="margin-top:10px">
          <h3 style="margin:0 0 6px">Queue line</h3>
          <p class="small">Click from the back of the line toward the scanner. Points snap to the 400×225 tile grid.</p>
          <div class="row">
            <div><label>Queue name</label><input id="accessQueueName" placeholder="North gate queue" /></div>
            <div><label>Scanner</label><select id="accessQueueGate"></select></div>
          </div>
          <div class="row" style="margin-top:8px">
            <button class="primary" onclick="finishDraftQueue()">Finish Queue</button>
            <button onclick="cancelDraftQueue()">Cancel Draw</button>
          </div>
        </div>
        <div class="row" style="margin-top:10px">
          <div><label>Zone name</label><input id="accessZoneName" placeholder="VIP Lawn" /></div>
          <div><label>Fill as</label><select id="accessZoneClass"><option value="ga">GA</option><option value="vip">VIP</option><option value="staff">Staff</option><option value="backstage">Backstage</option><option value="vendor">Vendor</option></select></div>
        </div>
        <div class="row" style="margin-top:8px;align-items:end">
          <div><label>Fill color</label><input id="accessZoneColor" type="color" value="#4caf50" style="width:100%;height:42px;padding:4px" /></div>
          <div><label>Opacity</label><input id="accessZoneOpacity" type="range" min="10" max="90" value="38" style="padding:0" /><div class="small" id="accessZoneOpacityLabel">38%</div></div>
          <div><label>Preview</label><div id="accessZoneColorPreview" class="zoneColorPreview"></div></div>
        </div>
        <div class="row" style="margin-top:8px;align-items:center">
          <span class="small">Presets:</span>
          <div id="accessZonePresets" class="row" style="gap:6px;flex:2"></div>
          <button onclick="saveZoneClassColorDefault()">Save Color For Class</button>
        </div>
        <p class="small">Use the layer toggles on the left to hide map clutter. Select a scanner, then use the fence heading slider to rotate snap points.</p>
        <div id="accessZoneEditor"></div>
        <div id="accessWorkLocationSection" class="hidden"></div>
        <h3 style="margin:14px 0 6px">Barriers</h3>
        <div class="list" id="accessBarrierList"></div>
        <h3 style="margin:14px 0 6px">Queues</h3>
        <div class="list" id="accessQueueList"></div>
        <h3 style="margin:14px 0 6px">Zones</h3>
        <div class="list" id="accessZoneList"></div>
        <div id="accessPortalEditor"></div>
      </section>
    </div></div>
  </div>
  </div>
  </div>
</div>
<script>
let events=[], currentEvent=null, currentTab='overview', mapClickMode=null, dataMode='pois';
let mapAnchors=[], pois=[], gates=[], wifiSweeps=[], surveyPaths=[], deviceSweeps=[]; let deviceSweepMode="BLE", deviceSweepView="readable", selectedDeviceSweepId=null, deviceSweepShowAll=true; let dashSearchMatches=[], dashSearchIndex=-1;
let mapOpacity=Number(localStorage.getItem('beaconDashMapOpacity')||100);
let mapZoom=Number(localStorage.getItem('beaconDashMapZoom')||100);
let mapPanX=Number(localStorage.getItem('beaconDashMapPanX')||0);
let mapPanY=Number(localStorage.getItem('beaconDashMapPanY')||0);
let mapPanLocked=localStorage.getItem('beaconDashMapPanLocked')!=='0';
const MAP_EDGE_SCROLL_MIN_ZOOM=110;
const MAP_EDGE_SCROLL_MARGIN=44;
const MAP_EDGE_SCROLL_MAX_SPEED=10;
let edgeScrollVx=0,edgeScrollVy=0,edgeScrollRaf=null;
function getMapStage(){return document.getElementById('mapStage')||document.getElementById('mapWrap');}
function getMapScale(){return mapZoom/100;}
function mapEdgeScrollActive(){return mapZoom>=MAP_EDGE_SCROLL_MIN_ZOOM;}
function mapEdgeScrollEnabled(){return mapEdgeScrollActive()&&!mapPanLocked;}
function updateMapPanLockButton(){const btn=document.getElementById('mapPanLockBtn'); if(!btn)return; btn.classList.toggle('unlocked',!mapPanLocked); btn.innerHTML=mapPanLocked?'&#128274;':'&#128275;'; btn.title=mapPanLocked?'Map pan locked — click to unlock edge scrolling':'Map pan unlocked — edge scrolling enabled';}
function toggleMapPanLock(){mapPanLocked=!mapPanLocked; localStorage.setItem('beaconDashMapPanLocked',mapPanLocked?'1':'0'); stopEdgeScroll(); updateMapPanLockButton(); applyMapTransform(); setStatus(mapPanLocked?'Map pan locked.':'Map pan unlocked — edge scrolling enabled.');}
function persistMapPan(){localStorage.setItem('beaconDashMapPanX',String(Math.round(mapPanX))); localStorage.setItem('beaconDashMapPanY',String(Math.round(mapPanY)));}
function clampMapPan(){const wrap=document.getElementById('mapWrap'); if(!wrap)return; const scale=getMapScale(); if(scale<=1){mapPanX=0; mapPanY=0; return;} const minX=wrap.clientWidth*(1-scale), minY=wrap.clientHeight*(1-scale); mapPanX=Math.min(0,Math.max(minX,mapPanX)); mapPanY=Math.min(0,Math.max(minY,mapPanY));}
function applyMapTransform(){const stage=getMapStage(), wrap=document.getElementById('mapWrap'); if(!stage||!wrap)return; const scale=getMapScale(); clampMapPan(); stage.style.transform=`translate(${mapPanX}px, ${mapPanY}px) scale(${scale})`; wrap.classList.toggle('mapEdgeScroll',mapEdgeScrollEnabled()); wrap.classList.toggle('mapPanLocked',mapPanLocked); if(!mapEdgeScrollEnabled())stopEdgeScroll(); updateMapPanLockButton();}
function stopEdgeScroll(){edgeScrollVx=0; edgeScrollVy=0; if(edgeScrollRaf){cancelAnimationFrame(edgeScrollRaf); edgeScrollRaf=null;}}
function edgeScrollFrame(){if(!edgeScrollVx&&!edgeScrollVy){edgeScrollRaf=null; return;} mapPanX+=edgeScrollVx; mapPanY+=edgeScrollVy; applyMapTransform(); persistMapPan(); edgeScrollRaf=requestAnimationFrame(edgeScrollFrame);}
function startEdgeScrollIfNeeded(){if(!edgeScrollRaf&&(edgeScrollVx||edgeScrollVy))edgeScrollRaf=requestAnimationFrame(edgeScrollFrame);}
function handleMapEdgeScroll(e){const wrap=document.getElementById('mapWrap'); if(!wrap||!mapEdgeScrollEnabled()){stopEdgeScroll(); return;} const rect=wrap.getBoundingClientRect(); const x=e.clientX-rect.left, y=e.clientY-rect.top; if(x<0||y<0||x>rect.width||y>rect.height){stopEdgeScroll(); return;} let vx=0, vy=0; if(x<MAP_EDGE_SCROLL_MARGIN)vx=((MAP_EDGE_SCROLL_MARGIN-x)/MAP_EDGE_SCROLL_MARGIN)*MAP_EDGE_SCROLL_MAX_SPEED; else if(x>rect.width-MAP_EDGE_SCROLL_MARGIN)vx=-((x-(rect.width-MAP_EDGE_SCROLL_MARGIN))/MAP_EDGE_SCROLL_MARGIN)*MAP_EDGE_SCROLL_MAX_SPEED; if(y<MAP_EDGE_SCROLL_MARGIN)vy=((MAP_EDGE_SCROLL_MARGIN-y)/MAP_EDGE_SCROLL_MARGIN)*MAP_EDGE_SCROLL_MAX_SPEED; else if(y>rect.height-MAP_EDGE_SCROLL_MARGIN)vy=-((y-(rect.height-MAP_EDGE_SCROLL_MARGIN))/MAP_EDGE_SCROLL_MARGIN)*MAP_EDGE_SCROLL_MAX_SPEED; edgeScrollVx=vx; edgeScrollVy=vy; if(vx||vy)startEdgeScrollIfNeeded(); else stopEdgeScroll();}
function setMapZoom(value){mapZoom=Math.max(100,Math.min(300,Number(value)||100)); localStorage.setItem('beaconDashMapZoom',String(mapZoom)); if(mapZoom<=100){mapPanX=0; mapPanY=0; localStorage.setItem('beaconDashMapPanX','0'); localStorage.setItem('beaconDashMapPanY','0'); stopEdgeScroll();} const val=document.getElementById('mapZoomValue'); if(val)val.textContent=mapZoom+'%'; const slider=document.getElementById('mapZoom'); if(slider&&Number(slider.value)!==mapZoom)slider.value=String(mapZoom); applyMapTransform();}
function resetMapView(){mapZoom=100; mapPanX=0; mapPanY=0; localStorage.setItem('beaconDashMapZoom','100'); localStorage.setItem('beaconDashMapPanX','0'); localStorage.setItem('beaconDashMapPanY','0'); stopEdgeScroll(); setMapZoom(100);}
function setMapOpacity(value){mapOpacity=Number(value)||100; localStorage.setItem('beaconDashMapOpacity',String(mapOpacity)); const img=document.querySelector('#mapStage img,#mapWrap img'); if(img)img.style.opacity=(mapOpacity/100).toFixed(2); const val=document.getElementById('mapOpacityValue'); if(val)val.textContent=mapOpacity+'%'; const slider=document.getElementById('mapOpacity'); if(slider&&Number(slider.value)!==mapOpacity)slider.value=String(mapOpacity);}
let remoteSurveyStart=null, remoteSurveyEnd=null, calibrationMapPoint=null;
let selectedKind=null, selectedId=null;
function setStatus(t){document.getElementById('status').textContent=t;}
function api(path, opts={}){return fetch(path,{headers:{'Content-Type':'application/json'},...opts}).then(async r=>{if(!r.ok){throw new Error(await r.text())} return r.status===204?null:r.json()})}
function setSelected(kind,id){selectedKind=kind; selectedId=id;}
function pct(n){return (n*100).toFixed(2)+'%'}
function escapeHtml(s){return String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}
function n3(v){return Number(v??0).toFixed(3)} function n4(v){return Number(v??0).toFixed(4)}
function setTab(tab, autoLoad=true){currentTab=tab; document.querySelectorAll('.tab').forEach(b=>b.classList.toggle('active',b.dataset.tab===tab)); document.querySelectorAll('[id^="tab-"]').forEach(s=>s.classList.add('hidden')); document.getElementById('tab-'+tab).classList.remove('hidden'); document.getElementById('toolTitle').textContent={overview:'Overview',wifi:'Wi-Fi Heatmaps',deviceSweeps:'Device Sweeps',remoteSurvey:'Remote Survey',calibration:'Calibration',access:'Access Control',data:'POIs / Survey',messages:'Messages'}[tab]||tab; clearOverlay(); if(typeof updateAccessMapPanel==='function')updateAccessMapPanel(); if(!autoLoad)return; if(tab==='wifi')loadWifiSweeps(); if(tab==='deviceSweeps')loadDeviceSweeps(); if(tab==='calibration')loadAnchors(); if(tab==='data')loadPois(); if(tab==='messages')loadMessageBoard(); if(tab==='access'&&typeof loadAccessLayout==='function')loadAccessLayout();}
document.querySelectorAll('.tab').forEach(b=>b.onclick=()=>setTab(b.dataset.tab));
function marker(x,y,cls,title,onclick){const el=document.createElement('div'); el.className='marker '+cls; if(selectedKind&&title&&title.includes(selectedId)){el.classList.add('selected'); if(dashSearchMatches.length)el.classList.add('searchHit');} el.style.left=pct(x); el.style.top=pct(y); el.title=title||''; if(onclick){el.onclick=(ev)=>{ev.stopPropagation(); onclick();};} getMapStage().appendChild(el); return el;}
function wifiColor(rssi){if(rssi>=-50)return '#00e676'; if(rssi>=-60)return '#9cff57'; if(rssi>=-67)return '#ffeb3b'; if(rssi>=-75)return '#ff9800'; return '#ff1744'}
function heat(x,y,rssi,title){const el=marker(x,y,'heat',title); el.style.background=wifiColor(rssi); el.style.boxShadow=`0 0 24px 10px ${wifiColor(rssi)}`; return el;}
function clearOverlay(){document.querySelectorAll('.marker,.deviceBlob,.deviceBlobLabel,.deviceBlobTag,.deviceBlobCard').forEach(e=>e.remove()); document.getElementById('pathSvg').innerHTML='';}
function stopCardControlEvent(ev){ev.stopPropagation();}
document.addEventListener('mousedown', ev=>{if(ev.target&&ev.target.closest&&ev.target.closest('select,input,textarea')) ev.stopPropagation();}, true);
document.addEventListener('click', ev=>{if(ev.target&&ev.target.closest&&ev.target.closest('select,input,textarea')) ev.stopPropagation();}, true);
function gateDeviceType(g){return (g.device_type||g.deviceType||'scanner').toLowerCase()}
function gateDeviceClass(g){const t=gateDeviceType(g); return (t==='handheld'||t==='ipad'||t==='scanner')?t:'scanner'}
function gateDeviceLabel(g){const t=gateDeviceClass(g); return t==='handheld'?'Handheld':(t==='ipad'?'iPad':'Scanner')}
function gateTypeOptions(selected){const v=(selected||'scanner').toLowerCase(); return `<option value="scanner" ${v==='scanner'||v==='portal'?'selected':''}>Scanner / reader box</option><option value="handheld" ${v==='handheld'?'selected':''}>Handheld</option><option value="ipad" ${v==='ipad'?'selected':''}>iPad</option>`}
function drawBase(){clearOverlay(); pois.forEach(p=>marker(p.map_x,p.map_y,'poi',`${p.id} ${p.name}`,()=>selectPoi(p.id))); gates.forEach(g=>{const el=marker(g.map_x,g.map_y,'gate '+gateDeviceClass(g),`${g.id} ${g.name} ${gateDeviceLabel(g)}`,()=>selectGate(g.id)); el.dataset.gateId=g.id;}); mapAnchors.forEach(a=>marker(a.map_x,a.map_y,'anchor',`anchor ${a.id}`,()=>selectAnchor(a.id))); if(dataMode==='survey')drawSurveyPaths();}
function mapXY(evt){const wrap=document.getElementById('mapWrap'); const rect=wrap.getBoundingClientRect(); const scale=getMapScale(); return {x:Math.max(0,Math.min(1,(evt.clientX-rect.left-mapPanX)/(rect.width*scale))), y:Math.max(0,Math.min(1,(evt.clientY-rect.top-mapPanY)/(rect.height*scale)))};}
document.getElementById('mapWrap').addEventListener('mousemove',handleMapEdgeScroll);
document.getElementById('mapWrap').addEventListener('mouseleave',stopEdgeScroll);
document.getElementById('mapWrap').addEventListener('click', e=>{const p=mapXY(e); if(!mapClickMode)return; if(mapClickMode==='surveyStart'){remoteSurveyStart=p; marker(p.x,p.y,'anchor','Survey start'); updateSurveyInfo(); setStatus('Survey start set.');} if(mapClickMode==='surveyEnd'){remoteSurveyEnd=p; marker(p.x,p.y,'anchor','Survey end'); updateSurveyInfo(); setStatus('Survey end set.');} if(mapClickMode==='calibration'){calibrationMapPoint=p; marker(p.x,p.y,'anchor','New calibration anchor'); document.getElementById('calMapInfo').textContent=`Map point: ${p.x.toFixed(4)}, ${p.y.toFixed(4)}`; setStatus('Calibration map point set.');} if(mapClickMode==='movePoi'&&selectedKind==='poi'){document.getElementById('editPoiMapX').value=p.x.toFixed(4); document.getElementById('editPoiMapY').value=p.y.toFixed(4); setStatus('POI map position updated in editor. Click Save POI.');} if(mapClickMode==='moveGate'&&selectedKind==='gate'){document.getElementById('editGateMapX').value=p.x.toFixed(4); document.getElementById('editGateMapY').value=p.y.toFixed(4); setStatus('Scanner map position updated in editor. Click Save Scanner.');} if(mapClickMode==='newGate'){document.getElementById('newGateMapX').value=p.x.toFixed(4); document.getElementById('newGateMapY').value=p.y.toFixed(4); setStatus('New scanner map position set. Click Create Scanner.');} if(mapClickMode==='newPoi'){document.getElementById('newPoiMapX').value=p.x.toFixed(4); document.getElementById('newPoiMapY').value=p.y.toFixed(4); setStatus('New POI map position set. Click Create POI.');} if(mapClickMode==='surveyEditStart'&&selectedKind==='survey'){document.getElementById('editSurveyStartX').value=p.x.toFixed(4); document.getElementById('editSurveyStartY').value=p.y.toFixed(4); setStatus('Survey start updated in editor. Click Save Survey.');} if(mapClickMode==='surveyEditEnd'&&selectedKind==='survey'){document.getElementById('editSurveyEndX').value=p.x.toFixed(4); document.getElementById('editSurveyEndY').value=p.y.toFixed(4); setStatus('Survey end updated in editor. Click Save Survey.');} if(mapClickMode==='moveSimLoc'&&selectedKind==='simLocation'){document.getElementById('editSimLocMapX').value=p.x.toFixed(4); document.getElementById('editSimLocMapY').value=p.y.toFixed(4); setStatus('Work location position updated in editor. Click Save.');} mapClickMode=null;});
function updateSurveyInfo(){document.getElementById('rsMapInfo').textContent=`Start: ${remoteSurveyStart?remoteSurveyStart.x.toFixed(4)+', '+remoteSurveyStart.y.toFixed(4):'not set'} • End: ${remoteSurveyEnd?remoteSurveyEnd.x.toFixed(4)+', '+remoteSurveyEnd.y.toFixed(4):'not set'}`}
async function init(){setMapOpacity(mapOpacity); setMapZoom(mapZoom); updateMapPanLockButton(); applyMapTransform(); events=await api('/events'); const wrap=document.getElementById('eventButtons'); wrap.innerHTML=''; events.forEach(ev=>{const b=document.createElement('button'); b.className='event'; b.innerHTML=`<b>${escapeHtml(ev.name)}</b><span>${escapeHtml(ev.description||'')}</span>`; b.onclick=()=>selectEvent(ev.id); wrap.appendChild(b)}); selectEvent((events.find(ev=>ev.id==='test_fest')||events[0]||{id:'test_fest'}).id);}
async function selectEvent(id){currentEvent=await api('/events/'+id); document.querySelectorAll('.event').forEach((b,i)=>b.classList.toggle('active',events[i]?.id===id)); document.getElementById('mapTitle').textContent=currentEvent.name+' Map'; const stage=getMapStage(); stage.querySelectorAll('img,.placeholder').forEach(e=>e.remove()); const img=document.createElement('img'); img.src=currentEvent.map_url; img.style.opacity=(mapOpacity/100).toFixed(2); img.onerror=()=>{const ph=document.createElement('div'); ph.className='placeholder'; ph.textContent='Map image missing'; stage.prepend(ph)}; stage.prepend(img); setMapOpacity(mapOpacity); setMapZoom(mapZoom); applyMapTransform(); selectedKind=null; selectedId=null; await refreshAll();}
async function refreshAll(){if(!currentEvent)return; try{[pois,gates,mapAnchors]=await Promise.all([api(`/events/${currentEvent.id}/pois`),api(`/events/${currentEvent.id}/scanners`),api(`/events/${currentEvent.id}/calibration-anchors`)]); try{surveyPaths=await api(`/events/${currentEvent.id}/survey-paths`)}catch(e){surveyPaths=[]} try{deviceSweeps=await api(`/events/${currentEvent.id}/device-map-sweeps`)}catch(e){deviceSweeps=[]} drawBase(); setStatus(`Loaded ${currentEvent.name}: ${pois.length} POIs, ${gates.length} gates, ${mapAnchors.length} anchors.`);}catch(e){setStatus('Refresh failed: '+e.message)}}
function selectPoi(id){setSelected('poi',id); setTab('data', false); dataMode='pois'; renderPois(); drawBase(); setStatus('Selected POI.');}
async function loadPois(){dataMode='pois'; pois=await api(`/events/${currentEvent.id}/pois`); if(selectedKind!=='poi'&&selectedKind!=='newPoi'){setSelected(null,null);} renderPois(); drawBase();}
function renderPois(){const list=document.getElementById('dataList'); const addCard=(selectedKind==='newPoi')?newPoiEditor():''; const poiCards=pois.map(p=>{const sel=selectedKind==='poi'&&selectedId===p.id; return `<div class="card ${sel?'selected':''}" id="poi-${p.id}" onclick="selectPoi('${p.id}')"><h3>${escapeHtml(p.name)}</h3><p>${escapeHtml(p.category)} • map ${n3(p.map_x)}, ${n3(p.map_y)}${p.latitude!=null&&p.longitude!=null?'<br>GPS '+p.latitude+', '+p.longitude:''}</p>${sel?poiEditor(p):''}</div>`}).join(''); list.innerHTML=addCard+(poiCards||'<p class="muted">No POIs.</p>');}
function poiEditor(p){return `<label>Name</label><input id="editPoiName" value="${escapeHtml(p.name)}"><label>Category</label><input id="editPoiCategory" value="${escapeHtml(p.category)}"><div class="row"><div><label>Map X</label><input id="editPoiMapX" value="${n4(p.map_x)}"></div><div><label>Map Y</label><input id="editPoiMapY" value="${n4(p.map_y)}"></div></div><div class="row"><div><label>Latitude</label><input id="editPoiLat" value="${p.latitude??''}"></div><div><label>Longitude</label><input id="editPoiLng" value="${p.longitude??''}"></div></div><div class="row"><button class="primary" onclick="event.stopPropagation(); savePoi('${p.id}')">Save POI</button><button onclick="event.stopPropagation(); mapClickMode='movePoi'; setStatus('Click map to move selected POI.')">Move on Map</button><button onclick="event.stopPropagation(); inferMapFromGps('editPoiLat','editPoiLng','editPoiMapX','editPoiMapY')">Infer Map from GPS</button><button onclick="event.stopPropagation(); inferGpsFromMap('editPoiMapX','editPoiMapY','editPoiLat','editPoiLng')">Infer GPS from Map</button><button class="danger" onclick="event.stopPropagation(); deletePoi('${p.id}')">Delete</button></div>`}
function startAddPoi(){setSelected('newPoi','new'); setTab('data',false); dataMode='pois'; renderPois(); drawBase(); setStatus('Create a new POI. Enter details or click Place on Map.');}
function newPoiEditor(){return `<div class="card selected"><h3>Add POI</h3><p class="muted">Create a new event POI for ${escapeHtml(currentEvent.name)}.</p><label>Name</label><input id="newPoiName" value="New POI"><label>Category</label><input id="newPoiCategory" value="Custom POIs"><div class="row"><div><label>Map X</label><input id="newPoiMapX" value="0.5000"></div><div><label>Map Y</label><input id="newPoiMapY" value="0.5000"></div></div><div class="row"><div><label>Latitude</label><input id="newPoiLat" placeholder="optional"></div><div><label>Longitude</label><input id="newPoiLng" placeholder="optional"></div></div><div class="row"><button class="primary" onclick="event.stopPropagation(); createPoi()">Create POI</button><button onclick="event.stopPropagation(); mapClickMode='newPoi'; setStatus('Click the map to place the new POI.')">Place on Map</button><button onclick="event.stopPropagation(); inferMapFromGps('newPoiLat','newPoiLng','newPoiMapX','newPoiMapY')">Infer Map from GPS</button><button onclick="event.stopPropagation(); inferGpsFromMap('newPoiMapX','newPoiMapY','newPoiLat','newPoiLng')">Infer GPS from Map</button><button onclick="event.stopPropagation(); selectedKind=null; selectedId=null; renderPois(); drawBase(); setStatus('Cancelled new POI.')">Cancel</button></div></div>`}
async function createPoi(){const lat=document.getElementById('newPoiLat').value.trim(), lng=document.getElementById('newPoiLng').value.trim(); const payload={name:document.getElementById('newPoiName').value||'New POI',category:document.getElementById('newPoiCategory').value||'Custom POIs',map_x:parseFloat(document.getElementById('newPoiMapX').value),map_y:parseFloat(document.getElementById('newPoiMapY').value),updated_by:'dash_poi_creator'}; if(lat!==''&&lng!==''){payload.latitude=parseFloat(lat); payload.longitude=parseFloat(lng); payload.accuracy_meters=0;} if(!Number.isFinite(payload.map_x)||!Number.isFinite(payload.map_y)){setStatus('Enter valid map X/Y.'); return;} const created=await api(`/events/${currentEvent.id}/pois`,{method:'POST',body:JSON.stringify(payload)}); pois=await api(`/events/${currentEvent.id}/pois`); setSelected('poi',created.id); renderPois(); drawBase(); setStatus('Created POI.');}
async function savePoi(id){const lat=document.getElementById('editPoiLat').value.trim(), lng=document.getElementById('editPoiLng').value.trim(); const payload={name:document.getElementById('editPoiName').value,category:document.getElementById('editPoiCategory').value,map_x:parseFloat(document.getElementById('editPoiMapX').value),map_y:parseFloat(document.getElementById('editPoiMapY').value),updated_by:'dash_editor'}; if(lat!==''&&lng!==''){payload.latitude=parseFloat(lat); payload.longitude=parseFloat(lng); payload.accuracy_meters=0;} await api(`/events/${currentEvent.id}/pois/${id}`,{method:'PUT',body:JSON.stringify(payload)}); pois=await api(`/events/${currentEvent.id}/pois`); setSelected('poi',id); renderPois(); drawBase(); setStatus('Saved POI.');}
async function deletePoi(id){if(!confirm('Delete this POI?'))return; await api(`/events/${currentEvent.id}/pois/${id}`,{method:'DELETE'}); selectedKind=null; selectedId=null; await loadPois(); setStatus('Deleted POI.');}
async function inferMapFromGps(latInputId,lngInputId,mapXInputId,mapYInputId){const lat=parseFloat(document.getElementById(latInputId).value), lng=parseFloat(document.getElementById(lngInputId).value); if(!Number.isFinite(lat)||!Number.isFinite(lng)){setStatus('Enter valid latitude and longitude first.');return} try{const result=await api(`/events/${currentEvent.id}/infer-map-position`,{method:'POST',body:JSON.stringify({latitude:lat,longitude:lng})}); document.getElementById(mapXInputId).value=Number(result.map_x_clamped??result.map_x).toFixed(4); document.getElementById(mapYInputId).value=Number(result.map_y_clamped??result.map_y).toFixed(4); setStatus(`Inferred map position from GPS using ${result.anchor_count} anchors.`);}catch(e){setStatus('Infer map position failed: '+e.message)}}
async function inferGpsFromMap(mapXInputId,mapYInputId,latInputId,lngInputId){const mx=parseFloat(document.getElementById(mapXInputId).value), my=parseFloat(document.getElementById(mapYInputId).value); if(!Number.isFinite(mx)||!Number.isFinite(my)){setStatus('Enter valid map X and map Y first.');return} try{const result=await api(`/events/${currentEvent.id}/infer-gps-position`,{method:'POST',body:JSON.stringify({map_x:mx,map_y:my})}); document.getElementById(latInputId).value=Number(result.latitude).toFixed(6); document.getElementById(lngInputId).value=Number(result.longitude).toFixed(6); setStatus(`Inferred GPS from map position using ${result.anchor_count} anchors.`);}catch(e){setStatus('Infer GPS failed: '+e.message)}}
function inferCalibrationGpsFromMap(){ if(!calibrationMapPoint){setStatus('Click Set Map Point, then click the map first.');return} document.getElementById('calMapInfo').textContent=`Map point: ${calibrationMapPoint.x.toFixed(4)}, ${calibrationMapPoint.y.toFixed(4)}`; try{api(`/events/${currentEvent.id}/infer-gps-position`,{method:'POST',body:JSON.stringify({map_x:calibrationMapPoint.x,map_y:calibrationMapPoint.y})}).then(result=>{document.getElementById('calLat').value=Number(result.latitude).toFixed(6); document.getElementById('calLng').value=Number(result.longitude).toFixed(6); setStatus(`Inferred GPS from selected map point using ${result.anchor_count} anchors.`)}).catch(e=>setStatus('Infer GPS failed: '+e.message));}catch(e){setStatus('Infer GPS failed: '+e.message)}}
async function loadMessageBoard(){const posts=await api(`/events/${currentEvent.id}/message-board`); document.getElementById('messageList').innerHTML=posts.map(m=>`<div class="card"><h3>${escapeHtml(m.subject)}</h3><p><b>${escapeHtml(m.name)}</b> <span class="muted">${escapeHtml(m.source||'dash')} • ${escapeHtml(m.created_at||'')}</span></p><p>${escapeHtml(m.body).replace(/\n/g,'<br>')}</p><button class="danger" onclick="deleteMessageBoard('${m.id}')">Delete</button></div>`).join('')||'<p class="muted">No messages yet.</p>'; setStatus(`Loaded ${posts.length} message board posts.`)}
async function postMessageBoard(){const name=document.getElementById('msgName').value.trim()||'Dash Tester'; const subject=document.getElementById('msgSubject').value.trim(); const body=document.getElementById('msgBody').value.trim(); if(!subject||!body){setStatus('Message needs a subject and body.');return} await api(`/events/${currentEvent.id}/message-board`,{method:'POST',body:JSON.stringify({name,subject,body,source:'dash'})}); document.getElementById('msgSubject').value=''; document.getElementById('msgBody').value=''; await loadMessageBoard(); setStatus('Posted message.')} 
async function deleteMessageBoard(id){if(!confirm('Delete this message?'))return; await api(`/events/${currentEvent.id}/message-board/${id}`,{method:'DELETE'}); await loadMessageBoard(); setStatus('Deleted message.')}
function selectGate(id){setSelected('gate',id); setTab('access', false); if(typeof setAccessTool==='function')setAccessTool('rfidDevices'); renderAccessRfidList(); if(typeof updateAccessMapPanel==='function')updateAccessMapPanel(); drawBase(); setStatus('Selected scanner.'); requestAnimationFrame(()=>{const card=document.getElementById('gate-'+id); if(card)card.scrollIntoView({block:'nearest',behavior:'smooth'});});}
async function loadGates(){gates=await api(`/events/${currentEvent.id}/scanners`); renderAccessRfidList(); drawBase();}
function renderAccessRfidList(){const list=document.getElementById('accessRfidList'); if(!list)return; const addCard=(selectedKind==='newGate')?newGateEditor():''; const gateCards=gates.map(g=>{const sel=selectedKind==='gate'&&selectedId===g.id; return `<div class="card ${sel?'selected':''}" id="gate-${g.id}" onclick="selectGate('${g.id}')"><h3>${escapeHtml(g.name)}</h3><p>${gateDeviceLabel(g)} • ${escapeHtml(g.connection_status)} • scans ${g.scan_count} • map ${n3(g.map_x)}, ${n3(g.map_y)}${g.latitude!=null&&g.longitude!=null?'<br>GPS '+g.latitude+', '+g.longitude:''}</p>${sel?gateEditor(g):''}</div>`}).join(''); list.innerHTML=addCard+(gateCards||'<p class="muted">No scanners yet. Click + Scanner.</p>'); if(typeof renderPortalEditor==='function')renderPortalEditor();}
function renderGates(){renderAccessRfidList();}
function startAddGate(){setSelected('newGate','new'); setTab('access',false); if(typeof setAccessTool==='function')setAccessTool('rfidDevices'); else renderAccessRfidList(); if(typeof updateAccessMapPanel==='function')updateAccessMapPanel(); drawBase(); setStatus('Create a new scanner. Select it, then use the fence heading slider to align snap points.');}
function newGateEditor(){return `<div class="card selected"><h3>Add Scanner</h3><p class="muted">Create a scanner, handheld, or tablet reader for ${escapeHtml(currentEvent.name)}.</p><label>Name</label><input id="newGateName" value="Scanner ${gates.length+1}"><label>Device Type</label><select id="newGateDeviceType" onpointerdown="event.stopPropagation()" onmousedown="event.stopPropagation()" onclick="event.stopPropagation()" onchange="event.stopPropagation()">${gateTypeOptions('portal')}</select><div class="row"><div><label>Map X</label><input id="newGateMapX" value="0.5000"></div><div><label>Map Y</label><input id="newGateMapY" value="0.5000"></div></div><div class="row"><div><label>Latitude</label><input id="newGateLat" placeholder="optional"></div><div><label>Longitude</label><input id="newGateLng" placeholder="optional"></div></div><div class="row"><div><label>Scan Count</label><input id="newGateScans" value="0"></div><div><label>IP Address</label><input id="newGateIp" placeholder="optional"></div></div><div class="row"><div><label>Status</label><select id="newGateStatus" onpointerdown="event.stopPropagation()" onmousedown="event.stopPropagation()" onclick="event.stopPropagation()" onchange="event.stopPropagation()"><option value="ONLINE">ONLINE</option><option value="OFFLINE">OFFLINE</option></select></div><div><label>Override</label><select id="newGateOverride" onpointerdown="event.stopPropagation()" onmousedown="event.stopPropagation()" onclick="event.stopPropagation()" onchange="event.stopPropagation()"><option value="NORMAL">NORMAL</option><option value="OFFLINE">OFFLINE</option></select></div></div><label>Fence heading (°)</label><input id="newGateFenceHeading" type="range" min="0" max="359" value="0" onpointerdown="event.stopPropagation()" onmousedown="event.stopPropagation()" onclick="event.stopPropagation()" oninput="event.stopPropagation(); syncNewGateFenceHeadingPreview(this.value)"><div class="small">Snap points sit on this fence line (0° = horizontal). Also adjustable in Map Layers sidebar.</div><div class="row"><button class="primary" onclick="event.stopPropagation(); createGate()">Create Device</button><button onclick="event.stopPropagation(); mapClickMode='newGate'; setStatus('Click the map to place the scanner.')">Place on Map</button><button onclick="event.stopPropagation(); inferMapFromGps('newGateLat','newGateLng','newGateMapX','newGateMapY')">Infer Map from GPS</button><button onclick="event.stopPropagation(); inferGpsFromMap('newGateMapX','newGateMapY','newGateLat','newGateLng')">Infer GPS from Map</button><button onclick="event.stopPropagation(); selectedKind=null; selectedId=null; renderAccessRfidList(); drawBase(); setStatus('Cancelled.')">Cancel</button></div></div>`}
async function createGate(){const lat=document.getElementById('newGateLat').value.trim(), lng=document.getElementById('newGateLng').value.trim(); const payload={name:document.getElementById('newGateName').value||'Scanner',device_type:document.getElementById('newGateDeviceType').value,map_x:parseFloat(document.getElementById('newGateMapX').value),map_y:parseFloat(document.getElementById('newGateMapY').value),scan_count:parseInt(document.getElementById('newGateScans').value||'0',10),connection_status:document.getElementById('newGateStatus').value,override_status:document.getElementById('newGateOverride').value,ip_address:document.getElementById('newGateIp').value||null,fence_heading_deg:parseInt(document.getElementById('newGateFenceHeading').value||'0',10),updated_by:'dash_gate_creator'}; if(lat!==''&&lng!==''){payload.latitude=parseFloat(lat); payload.longitude=parseFloat(lng); payload.accuracy_meters=0;} if(!Number.isFinite(payload.map_x)||!Number.isFinite(payload.map_y)){setStatus('Enter valid map X/Y.'); return;} const created=await api(`/events/${currentEvent.id}/scanners`,{method:'POST',body:JSON.stringify(payload)}); gates=await api(`/events/${currentEvent.id}/scanners`); setSelected('gate',created.id); setTab('access',false); if(typeof setAccessTool==='function')setAccessTool('rfidDevices'); renderAccessRfidList(); drawBase(); setStatus('Created scanner.');}
function gateSection(title,body,open){return `<details class="gateSection" ${open?'open':''} onclick="event.stopPropagation()" onmousedown="event.stopPropagation()"><summary onclick="event.stopPropagation()">${title}</summary><div class="gateSectionBody">${body}</div></details>`;}
function gateEditor(g){const health=`<div class="row"><div><label>Status</label><select id="editGateStatus" onpointerdown="event.stopPropagation()" onmousedown="event.stopPropagation()" onclick="event.stopPropagation()" onchange="event.stopPropagation()"><option value="ONLINE" ${g.connection_status==='ONLINE'?'selected':''}>ONLINE</option><option value="OFFLINE" ${g.connection_status==='OFFLINE'?'selected':''}>OFFLINE</option></select></div><div><label>Override</label><select id="editGateOverride" onpointerdown="event.stopPropagation()" onmousedown="event.stopPropagation()" onclick="event.stopPropagation()" onchange="event.stopPropagation()"><option value="NORMAL" ${g.override_status==='NORMAL'?'selected':''}>NORMAL</option><option value="OFFLINE" ${g.override_status==='OFFLINE'?'selected':''}>OFFLINE</option></select></div></div><div class="row"><div><label>Scan Count</label><input id="editGateScans" value="${g.scan_count??0}"></div><div><label>IP Address</label><input id="editGateIp" value="${escapeHtml(g.ip_address||'')}"></div></div>`; const location=`<div class="row"><div><label>Map X</label><input id="editGateMapX" value="${n4(g.map_x)}"></div><div><label>Map Y</label><input id="editGateMapY" value="${n4(g.map_y)}"></div></div><div class="row"><div><label>Latitude</label><input id="editGateLat" value="${g.latitude??''}"></div><div><label>Longitude</label><input id="editGateLng" value="${g.longitude??''}"></div></div><label>Fence heading (°) <span id="editGateFenceHeadingDeg">${Math.round(g.fence_heading_deg||0)}°</span></label><input id="editGateFenceHeading" type="range" min="0" max="359" value="${Math.round(g.fence_heading_deg||0)}" onpointerdown="event.stopPropagation()" onmousedown="event.stopPropagation()" onclick="event.stopPropagation()" oninput="event.stopPropagation(); syncGateFenceHeadingPreview(this.value)"><div class="small">Rotates snap points along the fence line. Also in Map Layers sidebar.</div><div class="row"><button onclick="event.stopPropagation(); mapClickMode='moveGate'; setStatus('Click map to move this scanner.')">Move on Map</button><button onclick="event.stopPropagation(); inferMapFromGps('editGateLat','editGateLng','editGateMapX','editGateMapY')">Infer Map from GPS</button><button onclick="event.stopPropagation(); inferGpsFromMap('editGateMapX','editGateMapY','editGateLat','editGateLng')">Infer GPS from Map</button></div>`; const rules=`<div id="gateRulesPanel"></div>`; return `<div onclick="event.stopPropagation()"><label>Name</label><input id="editGateName" value="${escapeHtml(g.name)}"><label>Device Type</label><select id="editGateDeviceType" onpointerdown="event.stopPropagation()" onmousedown="event.stopPropagation()" onclick="event.stopPropagation()" onchange="event.stopPropagation()">${gateTypeOptions(g.device_type||g.deviceType||'portal')}</select>${gateSection('Health',health,true)}${gateSection('Location',location,false)}${gateSection('Rules',rules,false)}<p class="small">Walk-through arrow: Map Layers panel.</p><div class="row"><button class="primary" onclick="event.stopPropagation(); saveGate('${g.id}')">Save Device</button><button class="danger" onclick="event.stopPropagation(); deleteGate('${g.id}')">Delete</button></div></div>`;}
async function saveGate(id){const lat=document.getElementById('editGateLat').value.trim(), lng=document.getElementById('editGateLng').value.trim(); const payload={name:document.getElementById('editGateName').value,device_type:document.getElementById('editGateDeviceType').value,map_x:parseFloat(document.getElementById('editGateMapX').value),map_y:parseFloat(document.getElementById('editGateMapY').value),scan_count:parseInt(document.getElementById('editGateScans').value||'0',10),connection_status:document.getElementById('editGateStatus').value,override_status:document.getElementById('editGateOverride').value,ip_address:document.getElementById('editGateIp').value,updated_by:'dash_gate_editor'}; if(lat!==''&&lng!==''){payload.latitude=parseFloat(lat); payload.longitude=parseFloat(lng); payload.accuracy_meters=0;} payload.fence_heading_deg=parseInt(document.getElementById('mapPortalFenceHeading')?.value||document.getElementById('editGateFenceHeading')?.value||'0',10); await api(`/events/${currentEvent.id}/scanners/${id}`,{method:'PUT',body:JSON.stringify(payload)}); gates=await api(`/events/${currentEvent.id}/scanners`); setSelected('gate',id); renderAccessRfidList(); drawBase(); setStatus('Saved scanner.');}
async function deleteGate(id){if(!confirm('Delete this scanner?'))return; await api(`/events/${currentEvent.id}/scanners/${id}`,{method:'DELETE'}); selectedKind=null; selectedId=null; await loadGates(); setStatus('Deleted scanner.');}
function selectAnchor(id){setSelected('anchor',id); setTab('calibration'); loadAnchors().then(()=>setStatus('Selected calibration anchor.'));}
async function loadAnchors(){mapAnchors=await api(`/events/${currentEvent.id}/calibration-anchors`); document.getElementById('anchorList').innerHTML=mapAnchors.map(a=>`<div class="card ${selectedKind==='anchor'&&selectedId===a.id?'selected':''}" onclick="selectAnchor('${a.id}')"><h3>Anchor</h3><p>map ${n4(a.map_x)}, ${n4(a.map_y)}<br>${a.latitude}, ${a.longitude}</p><button class="danger" onclick="event.stopPropagation(); deleteAnchor('${a.id}')">Delete</button></div>`).join('')||'<p class="muted">No anchors.</p>'; drawBase();}
async function deleteAnchor(id){if(!confirm('Delete this calibration anchor?'))return; await api(`/events/${currentEvent.id}/calibration-anchors/${id}`,{method:'DELETE'}); selectedKind=null; selectedId=null; await loadAnchors(); setStatus('Deleted calibration anchor.');}
async function saveCalibrationAnchor(){if(!calibrationMapPoint){setStatus('Click a map point first.');return} const lat=parseFloat(document.getElementById('calLat').value), lng=parseFloat(document.getElementById('calLng').value); if(!Number.isFinite(lat)||!Number.isFinite(lng)){setStatus('Enter valid latitude and longitude.');return} await api(`/events/${currentEvent.id}/calibration-anchors`,{method:'POST',body:JSON.stringify({map_x:calibrationMapPoint.x,map_y:calibrationMapPoint.y,latitude:lat,longitude:lng,accuracy_meters:0,created_by:'dash_remote'})}); calibrationMapPoint=null; document.getElementById('calMapInfo').textContent='Anchor saved.'; await loadAnchors(); setStatus('Saved remote calibration anchor.');}
function drawSurveyPaths(){const svg=document.getElementById('pathSvg'); surveyPaths.forEach(sp=>{if(sp.start_map_x==null||sp.start_map_y==null)return; marker(sp.start_map_x,sp.start_map_y,'survey',`${sp.id} start`,()=>selectSurveyPath(sp.id)); if(sp.end_map_x!=null&&sp.end_map_y!=null){marker(sp.end_map_x,sp.end_map_y,'survey',`${sp.id} end`,()=>selectSurveyPath(sp.id)); const line=document.createElementNS('http://www.w3.org/2000/svg','line'); line.setAttribute('x1',sp.start_map_x*1000); line.setAttribute('y1',sp.start_map_y*562); line.setAttribute('x2',sp.end_map_x*1000); line.setAttribute('y2',sp.end_map_y*562); line.setAttribute('class','pathSvgLine '+(selectedKind==='survey'&&selectedId===sp.id?'selected':'')); line.style.pointerEvents='auto'; line.onclick=(ev)=>{ev.stopPropagation(); selectSurveyPath(sp.id)}; svg.appendChild(line);}})}
function selectSurveyPath(id){setSelected('survey',id); setTab('data', false); dataMode='survey'; renderSurveyPaths(); drawBase(); setStatus('Selected survey path.');}
async function loadSurveyPaths(){dataMode='survey'; surveyPaths=await api(`/events/${currentEvent.id}/survey-paths`); renderSurveyPaths(); drawBase();}
function renderSurveyPaths(){const list=document.getElementById('dataList'); list.innerHTML=surveyPaths.map(sp=>{const sel=selectedKind==='survey'&&selectedId===sp.id; return `<div class="card ${sel?'selected':''}" id="survey-${sp.id}" onclick="selectSurveyPath('${sp.id}')"><h3>${escapeHtml(sp.name)}</h3><p>${escapeHtml(sp.survey_mode)} • ${escapeHtml(sp.path_type)} • ${sp.point_count} GPS points<br>start ${n3(sp.start_map_x)}, ${n3(sp.start_map_y)} ${sp.end_map_x!=null?'→ end '+n3(sp.end_map_x)+', '+n3(sp.end_map_y):''}</p>${sel?surveyEditor(sp):''}</div>`}).join('')||'<p class="muted">No survey paths.</p>';}
function surveyEditor(sp){return `<label>Name</label><input id="editSurveyName" value="${escapeHtml(sp.name)}"><div class="row"><div><label>Mode</label><select id="editSurveyMode"><option value="direct_path" ${sp.survey_mode==='direct_path'?'selected':''}>Direct Path</option><option value="area_walk" ${sp.survey_mode==='area_walk'?'selected':''}>Area Walk</option></select></div><div><label>Type</label><select id="editSurveyType"><option value="guest" ${sp.path_type==='guest'?'selected':''}>Guest</option><option value="staff" ${sp.path_type==='staff'?'selected':''}>Staff</option><option value="cart" ${sp.path_type==='cart'?'selected':''}>Cart</option><option value="restricted" ${sp.path_type==='restricted'?'selected':''}>Restricted</option><option value="emergency" ${sp.path_type==='emergency'?'selected':''}>Emergency</option></select></div></div><div class="row"><div><label>Start X</label><input id="editSurveyStartX" value="${n4(sp.start_map_x)}"></div><div><label>Start Y</label><input id="editSurveyStartY" value="${n4(sp.start_map_y)}"></div></div><div class="row"><div><label>End X</label><input id="editSurveyEndX" value="${sp.end_map_x??''}"></div><div><label>End Y</label><input id="editSurveyEndY" value="${sp.end_map_y??''}"></div></div><div class="row"><button class="primary" onclick="event.stopPropagation(); saveSurveyPath('${sp.id}')">Save Survey</button><button onclick="event.stopPropagation(); mapClickMode='surveyEditStart'; setStatus('Click map to set survey start.')">Move Start</button><button onclick="event.stopPropagation(); mapClickMode='surveyEditEnd'; setStatus('Click map to set survey end.')">Move End</button><button class="danger" onclick="event.stopPropagation(); deleteSurveyPath('${sp.id}')">Delete</button></div>`}
async function saveSurveyPath(id){const ex=document.getElementById('editSurveyEndX').value.trim(), ey=document.getElementById('editSurveyEndY').value.trim(); const payload={name:document.getElementById('editSurveyName').value,survey_mode:document.getElementById('editSurveyMode').value,path_type:document.getElementById('editSurveyType').value,start_map_x:parseFloat(document.getElementById('editSurveyStartX').value),start_map_y:parseFloat(document.getElementById('editSurveyStartY').value),end_map_x:ex===''?null:parseFloat(ex),end_map_y:ey===''?null:parseFloat(ey),updated_by:'dash_editor'}; await api(`/events/${currentEvent.id}/survey-paths/${id}`,{method:'PUT',body:JSON.stringify(payload)}); await loadSurveyPaths(); setSelected('survey',id); renderSurveyPaths(); drawBase(); setStatus('Saved survey path.');}
async function deleteSurveyPath(id){if(!confirm('Delete this survey path?'))return; await api(`/events/${currentEvent.id}/survey-paths/${id}`,{method:'DELETE'}); selectedKind=null; selectedId=null; await loadSurveyPaths(); setStatus('Deleted survey path.');}
function parseCoords(){const raw=document.getElementById('rsPoints').value.trim(); if(!raw)return[]; return raw.split(/\n+/).map((line,i)=>{const nums=line.match(/-?\d+(?:\.\d+)?/g)||[]; if(nums.length<2)throw new Error(`Line ${i+1} needs lat,lng`); return {seq:i,latitude:parseFloat(nums[0]),longitude:parseFloat(nums[1]),accuracy_meters:0,timestamp:new Date().toISOString()}})}
function previewRemoteSurvey(){drawBase(); const pts=parseCoords(); if(remoteSurveyStart)marker(remoteSurveyStart.x,remoteSurveyStart.y,'survey','Start'); if(remoteSurveyEnd)marker(remoteSurveyEnd.x,remoteSurveyEnd.y,'survey','End'); setStatus(`Preview ready: ${pts.length} GPS points. Save to store this remote survey path.`)}
async function saveRemoteSurvey(){if(!remoteSurveyStart){setStatus('Set a start point on the map first.');return} const mode=document.getElementById('rsMode').value; if(mode==='direct_path'&&!remoteSurveyEnd){setStatus('Direct Path needs an end point.');return} let pts; try{pts=parseCoords()}catch(e){setStatus(e.message);return} if(pts.length<1){setStatus('Paste at least one latitude,longitude point.');return} const payload={name:document.getElementById('rsName').value||'Remote Survey Path',survey_mode:mode,path_type:document.getElementById('rsType').value,start_map_x:remoteSurveyStart.x,start_map_y:remoteSurveyStart.y,end_map_x:remoteSurveyEnd?.x??null,end_map_y:remoteSurveyEnd?.y??null,distance_meters:0,created_by:'dash_remote_survey',points:pts}; const saved=await api(`/events/${currentEvent.id}/survey-paths`,{method:'POST',body:JSON.stringify(payload)}); await loadSurveyPaths(); setSelected('survey',saved.id); setTab('data'); renderSurveyPaths(); drawBase(); setStatus(`Saved remote survey with ${pts.length} GPS points.`)}

function deviceSweepCounts(s){
  const mode=deviceSweepMode==='BLE'?'BLE':'WIFI';
  const total=mode==='BLE'?(s.ble_total||0):(s.wifi_total||0);
  const strong=mode==='BLE'?(s.ble_strong||0):(s.wifi_strong||0);
  const medium=mode==='BLE'?(s.ble_medium||0):(s.wifi_medium||0);
  const weak=mode==='BLE'?(s.ble_weak||0):(s.wifi_weak||0);
  return {mode,total,strong,medium,weak};
}
function setDeviceSweepMode(mode){deviceSweepMode=mode; renderDeviceSweepList(); drawDeviceSweeps(); setStatus(`Viewing ${mode==='BLE'?'BLE':'Wi-Fi'} device blobs.`)}
function setDeviceSweepView(view){deviceSweepView=view; renderDeviceSweepList(); drawDeviceSweeps(); setStatus(view==='range'?'Viewing estimated signal range mode.':'Viewing readable exploded-count mode.');}
function viewAllDeviceSweeps(){selectedDeviceSweepId=null; deviceSweepShowAll=true; renderDeviceSweepList(); drawDeviceSweeps();}
function selectDeviceSweep(id){selectedDeviceSweepId=id; deviceSweepShowAll=false; renderDeviceSweepList(); drawDeviceSweeps(); setStatus('Selected device sweep.');}
function visibleDeviceSweeps(){if(deviceSweepShowAll)return deviceSweeps; if(!selectedDeviceSweepId)return []; return deviceSweeps.filter(s=>s.id===selectedDeviceSweepId);}
function haversineMeters(a,b){const R=6371000, toRad=d=>d*Math.PI/180; const dLat=toRad((b.latitude??0)-(a.latitude??0)), dLng=toRad((b.longitude??0)-(a.longitude??0)); const lat1=toRad(a.latitude??0), lat2=toRad(b.latitude??0); const h=Math.sin(dLat/2)**2+Math.cos(lat1)*Math.cos(lat2)*Math.sin(dLng/2)**2; return 2*R*Math.asin(Math.sqrt(h));}
function estimatedPxPerMeter(){
  const wrap=document.getElementById('mapWrap'); const rect=wrap.getBoundingClientRect(); const vals=[];
  for(let i=0;i<mapAnchors.length;i++)for(let j=i+1;j<mapAnchors.length;j++){
    const a=mapAnchors[i], b=mapAnchors[j];
    if(a.latitude==null||a.longitude==null||b.latitude==null||b.longitude==null)continue;
    const meters=haversineMeters(a,b); if(!Number.isFinite(meters)||meters<2)continue;
    const px=Math.hypot((a.map_x-b.map_x)*rect.width,(a.map_y-b.map_y)*rect.height); if(px>1)vals.push(px/meters);
  }
  if(!vals.length)return null; vals.sort((a,b)=>a-b); return vals[Math.floor(vals.length/2)];
}
function deviceRangeMeters(){
  // These are intentionally approximate phone-observable signal zones, not a true people-count radius.
  return deviceSweepMode==='BLE'
    ? {strong:8, medium:22, weak:55}
    : {strong:12, medium:35, weak:80};
}
function deviceSweepRadii(c){
  if(deviceSweepView==='range'){
    const m=deviceRangeMeters(); const ppm=estimatedPxPerMeter();
    if(ppm){
      const maxPx=Math.min(document.getElementById('mapWrap').clientWidth,document.getElementById('mapWrap').clientHeight)*0.32;
      return {strong:Math.max(12,Math.min(maxPx*.45,m.strong*ppm)), medium:Math.max(22,Math.min(maxPx*.72,m.medium*ppm)), weak:Math.max(34,Math.min(maxPx,m.weak*ppm)), meters:m, scaled:true};
    }
    return {strong:24, medium:54, weak:92, meters:m, scaled:false};
  }
  const r=Math.max(deviceSweepShowAll?30:44,Math.min(deviceSweepShowAll?86:118,28+Math.sqrt(Math.max(c.total,1))*7));
  return {strong:r*.32, medium:r*.62, weak:r, meters:null, scaled:false};
}
function drawOneDeviceSweep(s){
  const x=s.map_x??s.mapX, y=s.map_y??s.mapY; if(x==null||y==null)return;
  const c=deviceSweepCounts(s); const selected=s.id===selectedDeviceSweepId; const radii=deviceSweepRadii(c); const r=radii.weak;
  const blob=document.createElement('div');
  blob.className='deviceBlob'+(selected?' selected':'');
  blob.style.left=(x*100)+'%'; blob.style.top=(y*100)+'%'; blob.style.width=(r*2)+'px'; blob.style.height=(r*2)+'px';
  blob.style.opacity=deviceSweepShowAll&&!selected?'.52':'.78';
  const p1=Math.max(6,Math.min(30,(radii.strong/r)*100)); const p2=Math.max(p1+8,Math.min(62,(radii.medium/r)*100));
  blob.style.background=`radial-gradient(circle, rgba(24,185,87,.70) 0 ${p1}%, rgba(24,185,87,.18) ${p1+6}%, rgba(255,242,0,.34) ${p2-8}%, rgba(255,242,0,.18) ${p2+6}%, rgba(255,122,26,.20) 78%, rgba(255,122,26,0) 100%)`;
  blob.style.border=deviceSweepView==='range'?'1px solid rgba(255,255,255,.38)':'0';
  blob.title=`${s.name} • ${c.mode} total ${c.total} • ${deviceSweepView==='range'?'estimated range':'readable view'}`;
  blob.onclick=(ev)=>{ev.stopPropagation(); selectDeviceSweep(s.id)};
  getMapStage().appendChild(blob);
  const center=document.createElement('div'); center.className='marker anchor'; center.style.left=(x*100)+'%'; center.style.top=(y*100)+'%'; center.title='Exact sweep point'; center.onclick=(ev)=>{ev.stopPropagation(); selectDeviceSweep(s.id)}; getMapStage().appendChild(center);
  const labels=deviceSweepView==='range'
    ? [{v:c.strong,dy:-radii.strong*.45},{v:c.medium,dy:radii.medium*.18},{v:c.weak,dy:radii.weak*.48}]
    : [{v:c.strong,dy:-r*.18},{v:c.medium,dy:r*.16},{v:c.weak,dy:r*.49}];
  labels.forEach(o=>{const el=document.createElement('div'); el.className='deviceBlobLabel'; el.style.left=(x*100)+'%'; el.style.top=`calc(${y*100}% + ${o.dy}px)`; el.textContent=String(o.v); getMapStage().appendChild(el);});
  const card=document.createElement('div'); card.className='deviceBlobCard'+(selected?' selected':''); card.style.left=(x*100)+'%'; card.style.top=`calc(${y*100}% + ${r+10}px)`; card.onclick=(ev)=>{ev.stopPropagation(); selectDeviceSweep(s.id)};
  const rangeNote=deviceSweepView==='range'&&radii.meters?`<span class="deviceSweepStat">Range est. S~${radii.meters.strong}m / M~${radii.meters.medium}m / W~${radii.meters.weak}m${radii.scaled?'':' • unscaled'}</span>`:'';
  card.innerHTML=`<b>${escapeHtml(s.name||'Device Sweep')}<span class="deviceSweepModePill">${c.mode==='BLE'?'BLE':'Wi-Fi'}</span><span class="deviceSweepModePill">${deviceSweepView==='range'?'Range':'Readable'}</span></b><span class="deviceSweepStat">Total ${c.total} • S ${c.strong} / M ${c.medium} / W ${c.weak}</span>${rangeNote}`;
  getMapStage().appendChild(card);
}
function drawDeviceSweeps(){
  drawBase();
  const list=visibleDeviceSweeps();
  list.forEach(drawOneDeviceSweep);
  const label=deviceSweepShowAll?'all saved':(selectedDeviceSweepId?'selected':'no');
  setStatus(`Viewing ${list.length} ${label} device sweep blob${list.length===1?'':'s'} in ${deviceSweepMode} mode.`)
}
function renderDeviceSweepList(){
  const list=document.getElementById('deviceSweepList'); if(!list)return;
  document.getElementById('dsBleBtn')?.classList.toggle('primary',deviceSweepMode==='BLE');
  document.getElementById('dsWifiBtn')?.classList.toggle('primary',deviceSweepMode==='WIFI');
  document.getElementById('dsReadableBtn')?.classList.toggle('primary',deviceSweepView==='readable');
  document.getElementById('dsRangeBtn')?.classList.toggle('primary',deviceSweepView==='range');
  list.innerHTML=deviceSweeps.map(s=>{const c=deviceSweepCounts(s); const sel=s.id===selectedDeviceSweepId; return `<div class="card ${sel?'selected':''}" id="device-${s.id}" onclick="selectDeviceSweep('${s.id}')"><h3>${escapeHtml(s.name||'Device Sweep')}</h3><p><b>${c.mode==='BLE'?'BLE':'Wi-Fi'} total: ${c.total}</b><br>Strong ${c.strong} • Medium ${c.medium} • Weak ${c.weak}<br><span class="muted">View: ${deviceSweepView==='range'?'estimated signal range':'readable exploded counts'}</span><br><span class="muted">BLE ${s.ble_total||0} (${s.ble_strong||0}/${s.ble_medium||0}/${s.ble_weak||0}) • Wi-Fi ${s.wifi_total||0} (${s.wifi_strong||0}/${s.wifi_medium||0}/${s.wifi_weak||0})</span><br>map ${n4(s.map_x)}, ${n4(s.map_y)} • ${escapeHtml(s.created_at||'')}</p><div class="row"><button onclick="event.stopPropagation(); selectDeviceSweep('${s.id}')">View</button><button onclick="event.stopPropagation(); viewAllDeviceSweeps()">All</button><button class="danger" onclick="event.stopPropagation(); deleteDeviceSweep('${s.id}')">Delete</button></div></div>`}).join('')||'<p class="muted">No saved device sweeps yet.</p>';
}
async function loadDeviceSweeps(){deviceSweeps=await api(`/events/${currentEvent.id}/device-map-sweeps`); if(selectedDeviceSweepId&&!deviceSweeps.some(s=>s.id===selectedDeviceSweepId))selectedDeviceSweepId=null; renderDeviceSweepList(); drawDeviceSweeps()}
async function deleteDeviceSweep(id){if(!confirm('Delete this device sweep?'))return; await api(`/events/${currentEvent.id}/device-map-sweeps/${id}`,{method:'DELETE'}); if(selectedDeviceSweepId===id)selectedDeviceSweepId=null; await loadDeviceSweeps(); setStatus('Deleted device sweep.')}


function dashSearchItems(){
  const items=[];
  pois.forEach(p=>items.push({kind:'poi',id:p.id,label:p.name||'POI',detail:`POI • ${p.category||''}`,x:p.map_x,y:p.map_y,hay:`poi ${p.name||''} ${p.category||''} ${p.id||''}`}));
  gates.forEach(g=>items.push({kind:'gate',id:g.id,label:g.name||'Scanner',detail:`Scanner • ${gateDeviceLabel(g)} • ${g.connection_status||''}`,x:g.map_x,y:g.map_y,hay:`gate scanner ${g.name||''} ${gateDeviceLabel(g)} ${g.connection_status||''} ${g.id||''}`}));
  surveyPaths.forEach(sp=>items.push({kind:'survey',id:sp.id,label:sp.name||'Survey Path',detail:`Survey • ${sp.survey_mode||''} • ${sp.path_type||''}`,x:sp.start_map_x,y:sp.start_map_y,hay:`survey path ${sp.name||''} ${sp.survey_mode||''} ${sp.path_type||''} ${sp.id||''}`}));
  mapAnchors.forEach(a=>items.push({kind:'anchor',id:a.id,label:'Calibration Anchor',detail:`Anchor • ${n4(a.map_x)}, ${n4(a.map_y)}`,x:a.map_x,y:a.map_y,hay:`anchor calibration ${a.id||''} ${a.latitude||''} ${a.longitude||''}`}));
  deviceSweeps.forEach(ds=>items.push({kind:'deviceSweep',id:ds.id,label:ds.name||'Device Sweep',detail:`Device Sweep • BLE ${ds.ble_total||0} • Wi-Fi ${ds.wifi_total||0}`,x:ds.map_x,y:ds.map_y,hay:`device sweep devices ble wifi ${ds.name||''} ${ds.id||''}`}));
  return items;
}
async function ensureSearchData(){
  if(!currentEvent)return;
  if(!pois.length)try{pois=await api(`/events/${currentEvent.id}/pois`)}catch(e){}
  if(!gates.length)try{gates=await api(`/events/${currentEvent.id}/scanners`)}catch(e){}
  if(!surveyPaths.length)try{surveyPaths=await api(`/events/${currentEvent.id}/survey-paths`)}catch(e){}
  if(!mapAnchors.length)try{mapAnchors=await api(`/events/${currentEvent.id}/calibration-anchors`)}catch(e){}
  if(!deviceSweeps.length)try{deviceSweeps=await api(`/events/${currentEvent.id}/device-map-sweeps`)}catch(e){}
}
async function dashSearch(){
  const box=document.getElementById('dashSearchInput'); const q=(box?.value||'').trim().toLowerCase();
  if(!q){clearDashSearch();return;}
  await ensureSearchData();
  const terms=q.split(/\s+/).filter(Boolean);
  dashSearchMatches=dashSearchItems().filter(it=>terms.every(t=>(it.hay||'').toLowerCase().includes(t)||(it.label||'').toLowerCase().includes(t)||(it.detail||'').toLowerCase().includes(t)));
  dashSearchIndex=dashSearchMatches.length?0:-1;
  renderDashSearchResults();
  if(dashSearchMatches.length)focusDashSearchMatch(0); else setStatus(`No results for "${q}".`);
}
function renderDashSearchResults(){
  const wrap=document.getElementById('dashSearchResults'); if(!wrap)return;
  wrap.innerHTML=dashSearchMatches.slice(0,12).map((it,i)=>`<span class="searchChip ${i===dashSearchIndex?'active':''}" onclick="focusDashSearchMatch(${i})"><b>${escapeHtml(it.label)}</b> <span class="muted">${escapeHtml(it.detail)}</span></span>`).join('');
  if(dashSearchMatches.length>12)wrap.innerHTML+=`<span class="searchChip">+${dashSearchMatches.length-12} more</span>`;
}
function focusDashSearchMatch(i){
  if(!dashSearchMatches.length)return; dashSearchIndex=Math.max(0,Math.min(i,dashSearchMatches.length-1));
  const it=dashSearchMatches[dashSearchIndex]; renderDashSearchResults();
  if(it.kind==='poi'){selectPoi(it.id);}
  else if(it.kind==='gate'){selectGate(it.id);}
  else if(it.kind==='survey'){selectSurveyPath(it.id);}
  else if(it.kind==='anchor'){selectAnchor(it.id);}
  else if(it.kind==='deviceSweep'){setTab('deviceSweeps',false); selectedDeviceSweepId=it.id; deviceSweepShowAll=false; renderDeviceSweepList(); drawDeviceSweeps();}
  const el=document.getElementById(`${it.kind==='poi'?'poi':it.kind==='gate'?'gate':it.kind==='survey'?'survey':'device'}-${it.id}`);
  if(el)el.scrollIntoView({block:'center',behavior:'smooth'});
  setStatus(`Search selected: ${it.label} (${it.detail}).`);
}
function clearDashSearch(){dashSearchMatches=[]; dashSearchIndex=-1; const box=document.getElementById('dashSearchInput'); if(box)box.value=''; const r=document.getElementById('dashSearchResults'); if(r)r.innerHTML=''; drawBase();}

async function loadWifiSweeps(){wifiSweeps=await api(`/events/${currentEvent.id}/wifi-sweeps`); const list=document.getElementById('wifiList'); list.innerHTML=wifiSweeps.map(s=>`<div class="card"><h3>${escapeHtml(s.name)}</h3><p>${s.sample_count} samples • ${escapeHtml(s.target_ssid||'All networks')}<br>${escapeHtml(s.created_at||'')}</p><div class="row"><button onclick="viewWifiSweep('${s.id}')">View Heatmap</button><button class="danger" onclick="deleteWifiSweep('${s.id}')">Delete</button></div></div>`).join('')||'<p class="muted">No saved Wi-Fi sweeps yet.</p>';}
async function viewWifiSweep(id){const d=await api(`/events/${currentEvent.id}/wifi-sweeps/${id}`); drawBase(); let drawn=0; (d.samples||[]).forEach(s=>{const x=s.map_x??s.mapX, y=s.map_y??s.mapY; if(x!=null&&y!=null){heat(x,y,s.rssi_dbm,`${s.ssid||''} ${s.rssi_dbm} dBm`); drawn++}}); setStatus(`Viewing ${d.name}: ${drawn}/${(d.samples||[]).length} samples placed on map. Samples without map_x/map_y need calibration at record time.`)}
async function deleteWifiSweep(id){if(!confirm('Delete this Wi-Fi sweep?'))return; await api(`/events/${currentEvent.id}/wifi-sweeps/${id}`,{method:'DELETE'}); await loadWifiSweeps(); drawBase(); setStatus('Deleted Wi-Fi sweep.');}
init().catch(e=>setStatus('Startup failed: '+e.message));
</script>
<script src="/static/dash/access-control.js?v=3.12.0"></script>
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
            (DEFAULT_EVENT_ID,),
        ).fetchall()

    return [row_to_dict(row) for row in rows]


@app.get("/pois/{poi_id}")
def get_poi(poi_id: str):
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM pois WHERE id = ? AND event_id = ?",
            (poi_id, DEFAULT_EVENT_ID),
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
                payload.event_id or DEFAULT_EVENT_ID,
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


@app.get("/events/{event_id}/scanners")
def get_scanners(event_id: str):
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

    return [scanner_gate_row_to_dict(row) for row in rows]


@app.get("/events/{event_id}/wrstops-gates", include_in_schema=False)
def get_wrstops_gates_legacy(event_id: str):
    return get_scanners(event_id)


@app.post("/events/{event_id}/scanners")
def create_scanner(event_id: str, payload: ScannerCreate):
    gate_id = "scanner_" + uuid4().hex[:12]
    timestamp = now_iso()
    name = payload.name.strip() or "Scanner"
    device_type = normalize_gate_device_type(payload.device_type)
    scan_count = payload.scan_count if payload.scan_count is not None else 0
    connection_status = (payload.connection_status or "ONLINE").strip().upper() or "ONLINE"
    override_status = (payload.override_status or "NORMAL").strip().upper() or "NORMAL"

    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO wrstops_gates (
                id, event_id, name, device_type, map_x, map_y, latitude, longitude, accuracy_meters, scan_count,
                connection_status, ip_address, override_status, fence_heading_deg, portal_flow_flipped,
                created_at, updated_at, updated_by
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                gate_id,
                event_id,
                name,
                device_type,
                payload.map_x,
                payload.map_y,
                payload.latitude,
                payload.longitude,
                payload.accuracy_meters,
                scan_count,
                connection_status,
                payload.ip_address,
                override_status,
                normalize_fence_heading(payload.fence_heading_deg),
                1 if normalize_portal_flow_flipped(payload.portal_flow_flipped) else 0,
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

    return scanner_gate_row_to_dict(row)


@app.post("/events/{event_id}/wrstops-gates", include_in_schema=False)
def create_wrstops_gate_legacy(event_id: str, payload: WrstopsGateCreate):
    return create_scanner(event_id, payload)


@app.put("/events/{event_id}/scanners/{gate_id}")
def update_scanner(event_id: str, gate_id: str, payload: ScannerUpdate):
    with get_connection() as conn:
        existing = conn.execute(
            "SELECT * FROM wrstops_gates WHERE id = ? AND event_id = ?",
            (gate_id, event_id),
        ).fetchone()

        if existing is None:
            raise HTTPException(status_code=404, detail="Scanner not found")

        name = payload.name.strip() if payload.name is not None else existing["name"]
        device_type = normalize_gate_device_type(payload.device_type) if payload.device_type is not None else existing["device_type"]
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
        fence_heading_deg = (
            normalize_fence_heading(payload.fence_heading_deg)
            if payload.fence_heading_deg is not None
            else normalize_fence_heading(
                existing["fence_heading_deg"] if "fence_heading_deg" in existing.keys() else 0.0
            )
        )
        portal_flow_flipped = (
            normalize_portal_flow_flipped(payload.portal_flow_flipped)
            if payload.portal_flow_flipped is not None
            else normalize_portal_flow_flipped(
                existing["portal_flow_flipped"] if "portal_flow_flipped" in existing.keys() else 0
            )
        )

        conn.execute(
            """
            UPDATE wrstops_gates
            SET
                name = ?,
                device_type = ?,
                map_x = ?,
                map_y = ?,
                latitude = ?,
                longitude = ?,
                accuracy_meters = ?,
                scan_count = ?,
                connection_status = ?,
                ip_address = ?,
                override_status = ?,
                fence_heading_deg = ?,
                portal_flow_flipped = ?,
                updated_at = ?,
                updated_by = ?
            WHERE id = ? AND event_id = ?
            """,
            (
                name or existing["name"],
                device_type,
                map_x,
                map_y,
                latitude,
                longitude,
                accuracy_meters,
                scan_count,
                connection_status or "ONLINE",
                ip_address,
                override_status or "NORMAL",
                fence_heading_deg,
                1 if portal_flow_flipped else 0,
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

    return scanner_gate_row_to_dict(row)


@app.put("/events/{event_id}/wrstops-gates/{gate_id}", include_in_schema=False)
def update_wrstops_gate_legacy(event_id: str, gate_id: str, payload: WrstopsGateUpdate):
    return update_scanner(event_id, gate_id, payload)


@app.delete("/events/{event_id}/scanners/{gate_id}")
def delete_scanner(event_id: str, gate_id: str):
    with get_connection() as conn:
        existing = conn.execute(
            "SELECT * FROM wrstops_gates WHERE id = ? AND event_id = ?",
            (gate_id, event_id),
        ).fetchone()

        if existing is None:
            raise HTTPException(status_code=404, detail="Scanner not found")

        conn.execute(
            "DELETE FROM wrstops_gates WHERE id = ? AND event_id = ?",
            (gate_id, event_id),
        )
        conn.commit()

    return {"deleted": True, "id": gate_id, "event_id": event_id}


@app.delete("/events/{event_id}/wrstops-gates/{gate_id}", include_in_schema=False)
def delete_wrstops_gate_legacy(event_id: str, gate_id: str):
    return delete_scanner(event_id, gate_id)





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


@app.post("/events/{event_id}/infer-gps-position")
def infer_gps_position_for_event(event_id: str, payload: InferGpsPositionRequest):
    """Infer GPS latitude/longitude from normalized map_x/map_y using this event's calibration anchors."""
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
        latitude, longitude = apply_affine(transform, payload.map_x, payload.map_y)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {
        "ok": True,
        "event_id": event_id,
        "anchor_count": len(anchor_rows),
        "map_x": payload.map_x,
        "map_y": payload.map_y,
        "latitude": latitude,
        "longitude": longitude,
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




@app.get("/events/{event_id}/message-board")
def get_message_board_posts(event_id: str, limit: int = 100):
    limit = max(1, min(int(limit), 250))
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM message_board_posts
            WHERE event_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (event_id, limit),
        ).fetchall()
    return [message_board_post_row_to_dict(row) for row in rows]


@app.post("/events/{event_id}/message-board")
def create_message_board_post(event_id: str, payload: MessageBoardPostCreate):
    post_id = uuid4().hex
    created_at = now_iso()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO message_board_posts (
                id, event_id, name, subject, body, source, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                post_id,
                event_id,
                payload.name.strip(),
                payload.subject.strip(),
                payload.body.strip(),
                (payload.source or "unknown").strip(),
                created_at,
            ),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM message_board_posts WHERE id = ? AND event_id = ?",
            (post_id, event_id),
        ).fetchone()
    return message_board_post_row_to_dict(row)


@app.delete("/events/{event_id}/message-board/{post_id}")
def delete_message_board_post(event_id: str, post_id: str):
    with get_connection() as conn:
        existing = conn.execute(
            "SELECT * FROM message_board_posts WHERE id = ? AND event_id = ?",
            (post_id, event_id),
        ).fetchone()
        if existing is None:
            raise HTTPException(status_code=404, detail="Message board post not found")
        conn.execute(
            "DELETE FROM message_board_posts WHERE id = ? AND event_id = ?",
            (post_id, event_id),
        )
        conn.commit()
    return {"deleted": True, "id": post_id, "event_id": event_id}


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




@app.get("/events/{event_id}/device-map-sweeps")
def list_device_map_sweeps(event_id: str):
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM device_map_sweeps
            WHERE event_id = ?
            ORDER BY created_at DESC
            """,
            (event_id,),
        ).fetchall()
    return [device_map_sweep_row_to_dict(row) for row in rows]


@app.get("/events/{event_id}/device-map-sweeps/{sweep_id}")
def get_device_map_sweep(event_id: str, sweep_id: str):
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM device_map_sweeps WHERE id = ? AND event_id = ?",
            (sweep_id, event_id),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Device map sweep not found")
    return device_map_sweep_row_to_dict(row)


@app.post("/events/{event_id}/device-map-sweeps")
def create_device_map_sweep(event_id: str, payload: DeviceMapSweepCreate):
    sweep_id = "device_sweep_" + uuid4().hex[:12]
    timestamp = now_iso()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO device_map_sweeps (
                id, event_id, name, map_x, map_y, latitude, longitude,
                ble_total, ble_strong, ble_medium, ble_weak,
                wifi_total, wifi_strong, wifi_medium, wifi_weak,
                created_at, created_by
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                sweep_id,
                event_id,
                payload.name,
                payload.map_x,
                payload.map_y,
                payload.latitude,
                payload.longitude,
                payload.ble_total,
                payload.ble_strong,
                payload.ble_medium,
                payload.ble_weak,
                payload.wifi_total,
                payload.wifi_strong,
                payload.wifi_medium,
                payload.wifi_weak,
                timestamp,
                payload.created_by,
            ),
        )
        row = conn.execute(
            "SELECT * FROM device_map_sweeps WHERE id = ? AND event_id = ?",
            (sweep_id, event_id),
        ).fetchone()
    return device_map_sweep_row_to_dict(row)


@app.delete("/events/{event_id}/device-map-sweeps/{sweep_id}")
def delete_device_map_sweep(event_id: str, sweep_id: str):
    with get_connection() as conn:
        cur = conn.execute(
            "DELETE FROM device_map_sweeps WHERE id = ? AND event_id = ?",
            (sweep_id, event_id),
        )
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Device map sweep not found")
    return {"ok": True, "deleted_id": sweep_id}


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
