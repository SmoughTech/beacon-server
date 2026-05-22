from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional, List
import sqlite3
import os
from datetime import datetime, timezone
from uuid import uuid4


DATABASE_PATH = os.getenv("DATABASE_PATH", "beacon.db")

app = FastAPI(title="Beacon Server", version="2.0.0")

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

        # Android compatibility aliases:
        "mapX": row["map_x"],
        "mapY": row["map_y"],

        "is_custom": bool(row["is_custom"]),
        "latitude": row["latitude"],
        "longitude": row["longitude"],
        "accuracy_meters": row["accuracy_meters"],
        "updated_at": row["updated_at"],
        "updated_by": row["updated_by"],
    }


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
                updated_by TEXT
            )
            """
        )

        for poi in BUILT_IN_POIS:
            conn.execute(
                """
                INSERT INTO pois (
                    id, name, category, map_x, map_y, is_custom
                )
                VALUES (?, ?, ?, ?, ?, 0)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    category = excluded.category,
                    map_x = excluded.map_x,
                    map_y = excluded.map_y
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


@app.on_event("startup")
def startup():
    init_db()


@app.get("/health")
def health():
    return {
        "status": "ok",
        "database_path": DATABASE_PATH,
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

    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO pois (
                id, name, category, map_x, map_y, is_custom,
                latitude, longitude, accuracy_meters, updated_at, updated_by
            )
            VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?)
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
                updated_by = ?
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
                updated_by = ?
            WHERE id = ?
            """,
            (
                payload.latitude,
                payload.longitude,
                payload.accuracy_meters,
                now_iso(),
                payload.updated_by,
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
                detail="Built-in POIs cannot be deleted"
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
