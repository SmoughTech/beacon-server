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


app = FastAPI(title="Beacon Server", version="3.2.1")

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
    scan_count: Optional[int] = 0
    connection_status: Optional[str] = Field(default="ONLINE", max_length=40)
    ip_address: Optional[str] = Field(default=None, max_length=80)
    override_status: Optional[str] = Field(default="NORMAL", max_length=40)
    updated_by: Optional[str] = "android_wrstops"


class WrstopsGateUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    map_x: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    map_y: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    scan_count: Optional[int] = None
    connection_status: Optional[str] = Field(default=None, max_length=40)
    ip_address: Optional[str] = Field(default=None, max_length=80)
    override_status: Optional[str] = Field(default=None, max_length=40)
    updated_by: Optional[str] = "android_wrstops"


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
        "scan_count": row["scan_count"],
        "connection_status": row["connection_status"],
        "ip_address": row["ip_address"],
        "override_status": row["override_status"],
        "created_at": row["created_at"],
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

    return {
        "status": "ok",
        "database_path": DATABASE_PATH,
        "poi_count": count,
        "beacon_count": beacon_count,
        "wrstops_gate_count": wrstops_gate_count,
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
    :root{--bg:#08111d;--panel:#101c2b;--muted:#8ea2b8;--text:#f5f8fc;--line:rgba(255,255,255,.12);--blue:#5db7ff;--green:#6df7a7;--yellow:#ffd166;--red:#ff6b6b}
    *{box-sizing:border-box} body{margin:0;font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif;color:var(--text);background:radial-gradient(circle at top left,#14365a 0,var(--bg) 36rem)}
    button,input,select{font:inherit} button{border:1px solid var(--line);border-radius:12px;background:#1d334f;color:var(--text);padding:9px 12px;cursor:pointer} button:hover{filter:brightness(1.12)}
    button.primary{background:#1565c0;border-color:#4ea5ff} button.warn{background:#6c4a10;border-color:#ffd166} button.danger{background:#6b1e25;border-color:#ff6b6b} button.ghost{background:transparent}
    input,select{width:100%;border:1px solid var(--line);border-radius:10px;background:#07101b;color:var(--text);padding:10px;outline:none} input:focus,select:focus{border-color:var(--blue)} label{display:block;font-size:12px;color:var(--muted);margin-bottom:5px}
    .app{padding:18px;max-width:1500px;margin:0 auto}.topbar{display:flex;align-items:center;justify-content:space-between;gap:16px;margin-bottom:18px}.brand h1{margin:0;font-size:30px;letter-spacing:.04em}.brand p{margin:3px 0 0;color:var(--muted)}
    .eventCards{display:flex;gap:10px;flex-wrap:wrap}.eventCard{min-width:170px;text-align:left;background:rgba(16,28,43,.78)}.eventCard.active{outline:2px solid var(--green);background:#12334a}.eventCard b{display:block;font-size:16px}.eventCard span{color:var(--muted);font-size:12px}
    .grid{display:grid;grid-template-columns:minmax(320px,.9fr) minmax(480px,1.1fr);gap:16px}@media(max-width:980px){.grid{grid-template-columns:1fr}}
    .panel{background:rgba(16,28,43,.92);border:1px solid var(--line);border-radius:18px;overflow:hidden;box-shadow:0 14px 30px rgba(0,0,0,.28)}.panelHeader{display:flex;justify-content:space-between;align-items:center;gap:10px;padding:14px 16px;border-bottom:1px solid var(--line);background:rgba(255,255,255,.035)}.panelHeader h2{margin:0;font-size:18px}.panelBody{padding:14px}.tabs{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px}.tab.active{background:#224469;border-color:var(--blue)}
    .mapWrap{position:relative;width:100%;aspect-ratio:2500/1120;border-radius:16px;overflow:hidden;border:1px solid var(--line);background:linear-gradient(135deg,#315c3b,#89b979 45%,#d9d0ba 45%,#dedbd0 54%,#6ea062 54%);user-select:none;cursor:crosshair}.mapWrap.freedom_250{background:radial-gradient(ellipse at 50% 78%,rgba(255,255,255,.24),rgba(255,255,255,0) 26%),linear-gradient(90deg,rgba(255,255,255,.16) 0 1px,transparent 1px),linear-gradient(180deg,rgba(255,255,255,.12) 0 1px,transparent 1px),linear-gradient(135deg,#153756,#1e5a46 20%,#91bd79 45%,#d7d2c5 48%,#9ec786 56%,#174064);background-size:auto,9% 100%,100% 16%,auto}.mapWrap.lib_2026{background:radial-gradient(circle at 50% 50%,rgba(255,255,255,.25),transparent 20%),linear-gradient(135deg,#214f5e,#5e915f 34%,#dfc685 55%,#375b31)}
    .mapTitle{position:absolute;left:12px;top:10px;padding:6px 9px;border-radius:10px;background:rgba(0,0,0,.45);font-size:12px;color:white;font-weight:800}.whiteHouse{position:absolute;left:42%;top:41%;width:16%;height:10%;border-radius:10px;background:rgba(255,255,255,.86);border:2px solid rgba(6,20,34,.5);display:grid;place-items:center;color:#123;font-size:12px;font-weight:800}.ellipse{position:absolute;left:33%;top:68%;width:34%;height:23%;border-radius:50%;border:2px solid rgba(255,255,255,.35);background:rgba(125,183,105,.35)}
    .marker{position:absolute;transform:translate(-50%,-50%);display:grid;place-items:center;color:#07101b;font-size:10px;font-weight:900;box-shadow:0 5px 12px rgba(0,0,0,.35)}.marker.poi{width:20px;height:20px;border-radius:50%;background:var(--yellow);border:2px solid #fff}.marker.gate{width:22px;height:22px;border-radius:8px;background:var(--green);border:2px solid #07101b}.marker.offline{background:var(--red);color:white}.mapHint{color:var(--muted);font-size:12px;margin-top:8px}
    table{width:100%;border-collapse:collapse}th,td{padding:9px 8px;border-bottom:1px solid var(--line);text-align:left;font-size:13px;vertical-align:middle}th{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.06em}tr:hover td{background:rgba(255,255,255,.035)}.small{font-size:12px;color:var(--muted)}.actions{display:flex;gap:6px;flex-wrap:wrap}.actions button{padding:6px 8px;font-size:12px;border-radius:9px}.pill{display:inline-flex;align-items:center;gap:5px;padding:4px 8px;border-radius:999px;font-size:11px;font-weight:800;background:rgba(255,255,255,.08)}.pill.good{color:var(--green)}.pill.bad{color:var(--red)}.pill.warn{color:var(--yellow)}.status{margin:12px 0 0;padding:10px 12px;border-radius:12px;background:rgba(255,255,255,.07);color:var(--muted);font-size:13px}
    .modalBackdrop{position:fixed;inset:0;background:rgba(0,0,0,.62);display:none;align-items:center;justify-content:center;padding:16px;z-index:20}.modalBackdrop.show{display:flex}.modal{width:min(560px,100%);max-height:90vh;overflow:auto;border-radius:20px;background:#0d1826;border:1px solid var(--line);box-shadow:0 20px 60px rgba(0,0,0,.6)}.modalHeader{padding:16px;border-bottom:1px solid var(--line);display:flex;justify-content:space-between;align-items:center}.modalHeader h3{margin:0}.modalBody{padding:16px;display:grid;gap:12px}.formGrid{display:grid;grid-template-columns:1fr 1fr;gap:12px}.formGrid .wide{grid-column:1/-1}.modalFooter{padding:16px;border-top:1px solid var(--line);display:flex;gap:8px;justify-content:flex-end}
  </style>
</head>
<body>
<div class="app"><div class="topbar"><div class="brand"><h1>Beacon Dash</h1><p>Pure UI admin panel for events, POIs, WRSTOPS, and Quickfinder.</p></div><div class="eventCards" id="eventCards"></div></div>
<div class="grid"><section class="panel"><div class="panelHeader"><h2 id="mapHeader">Map Preview</h2><button class="ghost" onclick="refreshAll()">Refresh</button></div><div class="panelBody"><div class="mapWrap" id="mapWrap" onclick="handleMapClick(event)"><div class="mapTitle" id="mapTitle">Select event</div><div class="whiteHouse" id="whiteHouseBox" style="display:none">White House</div><div class="ellipse" id="ellipseBox" style="display:none"></div></div><div class="mapHint">Click the map while an Add/Edit modal is open to set map_x/map_y.</div><div class="status" id="status">Loading Dash...</div></div></section>
<section class="panel"><div class="panelHeader"><h2 id="dataHeader">Event Data</h2></div><div class="panelBody"><div class="tabs"><button class="tab active" id="tab-pois" onclick="setTab('pois')">POIs</button><button class="tab" id="tab-gates" onclick="setTab('gates')">WRSTOPS</button><button class="tab" id="tab-beacons" onclick="setTab('beacons')">Quickfinder</button></div><div id="tableActions"></div><div id="dataTable"></div></div></section></div></div>
<div class="modalBackdrop" id="modalBackdrop"><div class="modal"><div class="modalHeader"><h3 id="modalTitle">Edit</h3><button class="ghost" onclick="closeModal()">✕</button></div><div class="modalBody" id="modalBody"></div><div class="modalFooter" id="modalFooter"></div></div></div>
<script>
let events=[],selectedEventId='freedom_250',selectedTab='pois',pois=[],gates=[],beacons=[],modalMode=null,modalKind=null,modalId=null;
const $=id=>document.getElementById(id);function esc(v){return String(v??'').replace(/[&<>"']/g,s=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[s]));}function num(v,d=3){return v===null||v===undefined||v===''?'':Number(v).toFixed(d)}function setStatus(m){$('status').textContent=m}
async function api(path,opts={}){const res=await fetch(path,{headers:{'Content-Type':'application/json'},...opts});if(!res.ok){let detail='';try{detail=JSON.stringify(await res.json())}catch(e){detail=await res.text()}throw new Error(`${res.status}: ${detail}`)}return res.json()}
async function boot(){try{events=await api('/events')}catch(e){events=[{id:'lib_2026',name:"LIB '26",description:'LIB event map'},{id:'freedom_250',name:'Freedom 250',description:'Freedom 250 field test'}]}renderEvents();await refreshAll()}
function renderEvents(){$('eventCards').innerHTML=events.map(ev=>`<button class="eventCard ${ev.id===selectedEventId?'active':''}" onclick="selectEvent('${esc(ev.id)}')"><b>${esc(ev.name)}</b><span>${esc(ev.description||ev.id)}</span></button>`).join('')}
async function selectEvent(id){selectedEventId=id;renderEvents();await refreshAll()}function setTab(tab){selectedTab=tab;['pois','gates','beacons'].forEach(t=>$('tab-'+t).classList.toggle('active',t===tab));renderTable()}
async function refreshAll(){const ev=events.find(e=>e.id===selectedEventId)||{name:selectedEventId};$('mapHeader').textContent=`${ev.name} Map Preview`;$('dataHeader').textContent=`${ev.name} Data`;const wrap=$('mapWrap');wrap.className=`mapWrap ${selectedEventId}`;wrap.style.backgroundImage=ev.map_url?`url('${ev.map_url}')`:'';wrap.style.backgroundSize='contain';wrap.style.backgroundPosition='center';wrap.style.backgroundRepeat='no-repeat';$('mapTitle').textContent=ev.name;const showWh=selectedEventId==='freedom_250'&&!ev.map_url;$('whiteHouseBox').style.display=showWh?'grid':'none';$('ellipseBox').style.display=showWh?'block':'none';setStatus(`Loading ${ev.name}...`);try{const [p,g,b]=await Promise.all([api(`/events/${selectedEventId}/pois`),api(`/events/${selectedEventId}/wrstops-gates`),api('/beacons')]);pois=p;gates=g;beacons=b;renderMarkers();renderTable();setStatus(`Loaded ${pois.length} POIs, ${gates.length} WRSTOPS gates, ${beacons.length} Quickfinder codes.`)}catch(e){setStatus(`Load failed: ${e.message}`)}}
function renderMarkers(){document.querySelectorAll('.marker').forEach(m=>m.remove());const wrap=$('mapWrap');pois.forEach(p=>{const el=document.createElement('div');el.className='marker poi';el.style.left=`${p.map_x*100}%`;el.style.top=`${p.map_y*100}%`;el.title=p.name;el.textContent='P';wrap.appendChild(el)});gates.forEach(g=>{const el=document.createElement('div');const off=g.connection_status!=='ONLINE'||g.override_status==='OFFLINE';el.className=`marker gate ${off?'offline':''}`;el.style.left=`${g.map_x*100}%`;el.style.top=`${g.map_y*100}%`;el.title=g.name;el.textContent='W';wrap.appendChild(el)})}
function renderTable(){if(selectedTab==='pois')renderPois();if(selectedTab==='gates')renderGates();if(selectedTab==='beacons')renderBeacons()}
function renderPois(){$('tableActions').innerHTML=`<button class="primary" onclick="openPoiModal('add')">+ Add POI</button>`;$('dataTable').innerHTML=`<table><thead><tr><th>Name</th><th>Category</th><th>Map</th><th>GPS</th><th>Actions</th></tr></thead><tbody>${pois.map(p=>`<tr><td><b>${esc(p.name)}</b><div class="small">${esc(p.id)}</div></td><td>${esc(p.category)}</td><td>${num(p.map_x)}, ${num(p.map_y)}</td><td>${p.latitude?'<span class="pill good">GPS</span>':'<span class="pill warn">No GPS</span>'}</td><td><div class="actions"><button onclick="openPoiModal('edit','${esc(p.id)}')">Edit</button><button class="danger" onclick="deletePoi('${esc(p.id)}')">Delete</button></div></td></tr>`).join('')||'<tr><td colspan="5" class="small">No POIs saved for this event yet.</td></tr>'}</tbody></table>`}
function renderGates(){$('tableActions').innerHTML=`<button class="primary" onclick="openGateModal('add')">+ Add WRSTOPS Gate</button>`;$('dataTable').innerHTML=`<table><thead><tr><th>Name</th><th>Map</th><th>Status</th><th>Scans</th><th>Actions</th></tr></thead><tbody>${gates.map(g=>{const off=g.connection_status!=='ONLINE'||g.override_status==='OFFLINE';return `<tr><td><b>${esc(g.name)}</b><div class="small">${esc(g.id)}</div></td><td>${num(g.map_x)}, ${num(g.map_y)}</td><td><span class="pill ${off?'bad':'good'}">${off?'OFFLINE':'ONLINE'}</span></td><td>${esc(g.scan_count)}</td><td><div class="actions"><button onclick="openGateModal('edit','${esc(g.id)}')">Edit</button><button class="warn" onclick="toggleGate('${esc(g.id)}')">${off?'Online':'Offline'}</button><button onclick="resetScans('${esc(g.id)}')">Reset</button><button class="danger" onclick="deleteGate('${esc(g.id)}')">Delete</button></div></td></tr>`}).join('')||'<tr><td colspan="5" class="small">No WRSTOPS gates saved for this event yet.</td></tr>'}</tbody></table>`}
function renderBeacons(){$('tableActions').innerHTML=`<button onclick="refreshAll()">Refresh Codes</button>`;$('dataTable').innerHTML=`<table><thead><tr><th>Code</th><th>Name</th><th>GPS</th><th>Updated</th><th>Actions</th></tr></thead><tbody>${beacons.map(b=>`<tr><td><b>${esc(b.code)}</b></td><td>${esc(b.name)}</td><td>${num(b.latitude,6)}, ${num(b.longitude,6)}</td><td class="small">${esc(b.updated_at)}</td><td><button class="danger" onclick="deleteBeacon('${esc(b.code)}')">Delete</button></td></tr>`).join('')||'<tr><td colspan="5" class="small">No active Quickfinder codes.</td></tr>'}</tbody></table>`}
function openPoiModal(mode,id=null){const p=id?pois.find(x=>x.id===id):null;modalMode=mode;modalKind='poi';modalId=id;const x=p?.map_x??0.5,y=p?.map_y??0.5;$('modalTitle').textContent=mode==='add'?'Add POI':'Edit POI';$('modalBody').innerHTML=`<div class="formGrid"><div class="wide"><label>Name</label><input id="f-name" value="${esc(p?.name||'')}" placeholder="Box Office" /></div><div class="wide"><label>Category</label><input id="f-category" value="${esc(p?.category||'Custom POIs')}" /></div><div><label>Map X</label><input id="f-mapx" type="number" min="0" max="1" step="0.001" value="${x}" /></div><div><label>Map Y</label><input id="f-mapy" type="number" min="0" max="1" step="0.001" value="${y}" /></div><div><label>Latitude optional</label><input id="f-lat" type="number" step="0.000001" value="${p?.latitude??''}" /></div><div><label>Longitude optional</label><input id="f-lng" type="number" step="0.000001" value="${p?.longitude??''}" /></div></div>`;$('modalFooter').innerHTML=`<button class="ghost" onclick="closeModal()">Cancel</button><button class="primary" onclick="savePoi()">Save POI</button>`;$('modalBackdrop').classList.add('show')}
function openGateModal(mode,id=null){const g=id?gates.find(x=>x.id===id):null;modalMode=mode;modalKind='gate';modalId=id;const x=g?.map_x??0.5,y=g?.map_y??0.5;$('modalTitle').textContent=mode==='add'?'Add WRSTOPS Gate':'Edit WRSTOPS Gate';$('modalBody').innerHTML=`<div class="formGrid"><div class="wide"><label>Gate Name</label><input id="f-name" value="${esc(g?.name||'')}" placeholder="Gate 1" /></div><div><label>Map X</label><input id="f-mapx" type="number" min="0" max="1" step="0.001" value="${x}" /></div><div><label>Map Y</label><input id="f-mapy" type="number" min="0" max="1" step="0.001" value="${y}" /></div><div><label>Scan Count</label><input id="f-scans" type="number" min="0" step="1" value="${g?.scan_count??0}" /></div><div><label>IP Address optional</label><input id="f-ip" value="${esc(g?.ip_address||'')}" placeholder="10.20.4.16" /></div><div><label>Connection</label><select id="f-status"><option ${g?.connection_status!=='OFFLINE'?'selected':''}>ONLINE</option><option ${g?.connection_status==='OFFLINE'?'selected':''}>OFFLINE</option></select></div><div><label>Override</label><select id="f-override"><option ${g?.override_status!=='OFFLINE'?'selected':''}>NORMAL</option><option ${g?.override_status==='OFFLINE'?'selected':''}>OFFLINE</option></select></div></div>`;$('modalFooter').innerHTML=`<button class="ghost" onclick="closeModal()">Cancel</button><button class="primary" onclick="saveGate()">Save Gate</button>`;$('modalBackdrop').classList.add('show')}
function closeModal(){$('modalBackdrop').classList.remove('show');modalMode=modalKind=modalId=null}function handleMapClick(ev){if(!modalKind)return;const r=$('mapWrap').getBoundingClientRect();const x=Math.max(0,Math.min(1,(ev.clientX-r.left)/r.width));const y=Math.max(0,Math.min(1,(ev.clientY-r.top)/r.height));if($('f-mapx')&&$('f-mapy')){$('f-mapx').value=x.toFixed(3);$('f-mapy').value=y.toFixed(3)}setStatus(`Picked map position ${x.toFixed(3)}, ${y.toFixed(3)}.`)}
async function savePoi(){const payload={name:$('f-name').value.trim()||'New POI',category:$('f-category').value.trim()||'Custom POIs',map_x:Number($('f-mapx').value),map_y:Number($('f-mapy').value),updated_by:'dash'};if($('f-lat').value)payload.latitude=Number($('f-lat').value);if($('f-lng').value)payload.longitude=Number($('f-lng').value);try{if(modalMode==='add')await api(`/events/${selectedEventId}/pois`,{method:'POST',body:JSON.stringify(payload)});else await api(`/events/${selectedEventId}/pois/${modalId}`,{method:'PUT',body:JSON.stringify(payload)});closeModal();await refreshAll()}catch(e){setStatus(`Save POI failed: ${e.message}`)}}
async function saveGate(){const payload={name:$('f-name').value.trim()||'Gate',map_x:Number($('f-mapx').value),map_y:Number($('f-mapy').value),scan_count:Number($('f-scans').value||0),ip_address:$('f-ip').value.trim()||null,connection_status:$('f-status').value,override_status:$('f-override').value,updated_by:'dash'};try{if(modalMode==='add')await api(`/events/${selectedEventId}/wrstops-gates`,{method:'POST',body:JSON.stringify(payload)});else await api(`/events/${selectedEventId}/wrstops-gates/${modalId}`,{method:'PUT',body:JSON.stringify(payload)});closeModal();await refreshAll()}catch(e){setStatus(`Save gate failed: ${e.message}`)}}
async function deletePoi(id){if(!confirm('Delete this POI?'))return;try{await api(`/events/${selectedEventId}/pois/${id}`,{method:'DELETE'});await refreshAll()}catch(e){setStatus(`Delete POI failed: ${e.message}`)}}async function deleteGate(id){if(!confirm('Delete this WRSTOPS gate?'))return;try{await api(`/events/${selectedEventId}/wrstops-gates/${id}`,{method:'DELETE'});await refreshAll()}catch(e){setStatus(`Delete gate failed: ${e.message}`)}}async function toggleGate(id){const g=gates.find(x=>x.id===id);if(!g)return;const off=g.connection_status!=='ONLINE'||g.override_status==='OFFLINE';const payload={...g,connection_status:off?'ONLINE':'OFFLINE',override_status:off?'NORMAL':'OFFLINE',updated_by:'dash'};try{await api(`/events/${selectedEventId}/wrstops-gates/${id}`,{method:'PUT',body:JSON.stringify(payload)});await refreshAll()}catch(e){setStatus(`Toggle gate failed: ${e.message}`)}}async function resetScans(id){const g=gates.find(x=>x.id===id);if(!g)return;try{await api(`/events/${selectedEventId}/wrstops-gates/${id}`,{method:'PUT',body:JSON.stringify({...g,scan_count:0,updated_by:'dash'})});await refreshAll()}catch(e){setStatus(`Reset scans failed: ${e.message}`)}}async function deleteBeacon(code){if(!confirm(`Delete Quickfinder code ${code}?`))return;try{await api(`/beacons/${code}`,{method:'DELETE'});await refreshAll()}catch(e){setStatus(`Delete code failed: ${e.message}`)}}
boot();
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
                id, event_id, name, map_x, map_y, scan_count,
                connection_status, ip_address, override_status,
                created_at, updated_at, updated_by
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                gate_id,
                event_id,
                name,
                payload.map_x,
                payload.map_y,
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
