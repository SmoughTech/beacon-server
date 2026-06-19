"""Scanner table name and schema migration helpers."""

from __future__ import annotations

import sqlite3

SCANNERS_TABLE = "scanners"
# One-time SQLite legacy identifiers (old table/column/device_type values only).
LEGACY_SCANNERS_TABLE = "wrstops_gates"


def migrate_scanners_schema(conn: sqlite3.Connection) -> None:
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }

    if SCANNERS_TABLE not in tables:
        if LEGACY_SCANNERS_TABLE in tables:
            conn.execute(f"ALTER TABLE {LEGACY_SCANNERS_TABLE} RENAME TO {SCANNERS_TABLE}")
        else:
            conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {SCANNERS_TABLE} (
                    id TEXT PRIMARY KEY,
                    event_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    device_type TEXT NOT NULL DEFAULT 'scanner',
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
        f"CREATE INDEX IF NOT EXISTS idx_scanners_event_id ON {SCANNERS_TABLE}(event_id)"
    )

    cols = {
        row["name"]
        for row in conn.execute(f"PRAGMA table_info({SCANNERS_TABLE})").fetchall()
    }

    if "latitude" not in cols:
        conn.execute(f"ALTER TABLE {SCANNERS_TABLE} ADD COLUMN latitude REAL")
    if "longitude" not in cols:
        conn.execute(f"ALTER TABLE {SCANNERS_TABLE} ADD COLUMN longitude REAL")
    if "accuracy_meters" not in cols:
        conn.execute(f"ALTER TABLE {SCANNERS_TABLE} ADD COLUMN accuracy_meters REAL")
    if "device_type" not in cols:
        conn.execute(
            f"ALTER TABLE {SCANNERS_TABLE} ADD COLUMN device_type TEXT NOT NULL DEFAULT 'scanner'"
        )
    if "fence_heading_deg" not in cols:
        conn.execute(
            f"ALTER TABLE {SCANNERS_TABLE} ADD COLUMN fence_heading_deg REAL NOT NULL DEFAULT 0"
        )
    if "flow_flipped" not in cols:
        if "portal_flow_flipped" in cols:
            conn.execute(
                f"ALTER TABLE {SCANNERS_TABLE} RENAME COLUMN portal_flow_flipped TO flow_flipped"
            )
        else:
            conn.execute(
                f"ALTER TABLE {SCANNERS_TABLE} ADD COLUMN flow_flipped INTEGER NOT NULL DEFAULT 0"
            )

    conn.execute(
        f"""
        UPDATE {SCANNERS_TABLE}
        SET device_type = 'scanner'
        WHERE lower(device_type) IN (
            'portal', 'portal_reader', 'rfid_reader', 'box', 'reader', 'rfid'
        )
        """
    )
