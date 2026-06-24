"""Event registry stored in SQLite (replaces hardcoded EVENTS list)."""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timezone
from typing import Callable

EVENTS_TABLE = "events"

DEFAULT_SEED_EVENTS = [
    {
        "id": "test_fest",
        "name": "Test Fest",
        "map_name": "test_fest_map",
        "description": "Test Fest park map for SiteOps, scanners, and access control.",
    },
]

ALLOWED_MAP_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def slugify_event_id(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower().strip())
    slug = slug.strip("_")
    return (slug or "event")[:64]


def unique_event_id(conn: sqlite3.Connection, base: str) -> str:
    candidate = base
    suffix = 2
    while conn.execute(
        f"SELECT 1 FROM {EVENTS_TABLE} WHERE id = ?",
        (candidate,),
    ).fetchone():
        candidate = f"{base}_{suffix}"[:64]
        suffix += 1
    return candidate


def init_events_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {EVENTS_TABLE} (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            map_name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )

    cols = {
        row["name"]
        for row in conn.execute(f"PRAGMA table_info({EVENTS_TABLE})").fetchall()
    }
    if "map_width_ft" not in cols:
        conn.execute(
            f"ALTER TABLE {EVENTS_TABLE} ADD COLUMN map_width_ft REAL NOT NULL DEFAULT 800"
        )
    if "map_height_ft" not in cols:
        conn.execute(
            f"ALTER TABLE {EVENTS_TABLE} ADD COLUMN map_height_ft REAL NOT NULL DEFAULT 450"
        )
    if "person_map_x" not in cols:
        conn.execute(f"ALTER TABLE {EVENTS_TABLE} ADD COLUMN person_map_x REAL")
    if "person_map_y" not in cols:
        conn.execute(f"ALTER TABLE {EVENTS_TABLE} ADD COLUMN person_map_y REAL")
    if "person_height_norm" not in cols:
        conn.execute(f"ALTER TABLE {EVENTS_TABLE} ADD COLUMN person_height_norm REAL")
    if "person_height_ft" not in cols:
        conn.execute(
            f"ALTER TABLE {EVENTS_TABLE} ADD COLUMN person_height_ft REAL NOT NULL DEFAULT 5.75"
        )

    count = conn.execute(f"SELECT COUNT(*) AS c FROM {EVENTS_TABLE}").fetchone()["c"]
    if count:
        return

    ts = now_iso()
    for event in DEFAULT_SEED_EVENTS:
        conn.execute(
            f"""
            INSERT INTO {EVENTS_TABLE} (
                id, name, map_name, description, created_at, updated_at,
                map_width_ft, map_height_ft, person_height_ft
            )
            VALUES (?, ?, ?, ?, ?, ?, 800, 450, 5.75)
            """,
            (
                event["id"],
                event["name"],
                event["map_name"],
                event["description"],
                ts,
                ts,
            ),
        )


def event_row_to_dict(row: sqlite3.Row, map_url_for: Callable[[str], str]) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "map_name": row["map_name"],
        "description": row["description"],
        "map_url": map_url_for(row["map_name"]),
        "map_width_ft": row["map_width_ft"] if "map_width_ft" in row.keys() else 800,
        "map_height_ft": row["map_height_ft"] if "map_height_ft" in row.keys() else 450,
        "person_map_x": row["person_map_x"] if "person_map_x" in row.keys() else None,
        "person_map_y": row["person_map_y"] if "person_map_y" in row.keys() else None,
        "person_height_norm": row["person_height_norm"] if "person_height_norm" in row.keys() else None,
        "person_height_ft": row["person_height_ft"] if "person_height_ft" in row.keys() else 5.75,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def query_all_events(conn: sqlite3.Connection, map_url_for: Callable[[str], str]) -> list[dict]:
    rows = conn.execute(
        f"""
        SELECT * FROM {EVENTS_TABLE}
        ORDER BY name COLLATE NOCASE ASC
        """
    ).fetchall()
    return [event_row_to_dict(row, map_url_for) for row in rows]


def query_event_by_id(
    conn: sqlite3.Connection,
    event_id: str,
    map_url_for: Callable[[str], str],
) -> dict | None:
    row = conn.execute(
        f"SELECT * FROM {EVENTS_TABLE} WHERE id = ?",
        (event_id,),
    ).fetchone()
    if row is None:
        return None
    return event_row_to_dict(row, map_url_for)


def map_extension_from_filename(filename: str) -> str:
    lower = (filename or "").lower()
    for ext in ALLOWED_MAP_EXTENSIONS:
        if lower.endswith(ext):
            return ext
    return ".png"


def map_extension_from_content_type(content_type: str | None) -> str | None:
    if not content_type:
        return None
    ct = content_type.lower().split(";")[0].strip()
    return {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/webp": ".webp",
    }.get(ct)
