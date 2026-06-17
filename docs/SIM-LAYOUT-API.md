# Sim-layout API

Beacon desktop sim loads event operational layouts via a single consolidated endpoint.

## Endpoint

```
GET /events/{event_id}/sim-layout
```

Returns JSON describing barriers, zones, scanners, calibration anchors, precomputed navmesh, and scanner graph.

## Coordinate system

| Field | Value |
|-------|-------|
| Space | Normalized `map_x` / `map_y` in `[0.0, 1.0]` |
| Origin | Top-left of map image |
| Navmesh grid | 400 × 225 cells (matches Dash flood-fill grid) |
| Cell indexing | Row-major: `index = gy * width + gx` |

## Navmesh encoding

```json
"navmesh": {
  "encoding": "base64",
  "width": 400,
  "height": 225,
  "walkable_value": 0,
  "blocked_value": 1,
  "data": "<base64 raw bytes, length = width * height>"
}
```

- `0` = walkable
- `1` = blocked (barrier or scanner virtual wall)

Navmesh is computed server-side in [`geometry.py`](geometry.py) using the same rasterization rules as Dash [`access-control.js`](static/dash/access-control.js).

## Scanner graph

Derived from scanner access fields on gate records:

- **Nodes:** `outside`, each zone (`kind: zone`), each scanner (`kind: scanner`)
- **Edges:** zone-to-zone transitions via a scanner, respecting `direction` and `allowed_classes`

```json
"scanner_graph": {
  "nodes": [
    { "id": "outside", "kind": "outside", "label": "Outside" },
    { "id": "zone_abc", "kind": "zone", "label": "GA Lawn", "zone_class": "ga", "centroid": { "x": 0.5, "y": 0.6 } },
    { "id": "scanner_xyz", "kind": "scanner", "label": "Main Scanner", "map_x": 0.42, "map_y": 0.55 }
  ],
  "edges": [
    { "from": "zone_ga", "to": "zone_vip", "via_scanner": "scanner_xyz", "allowed_classes": ["ga", "vip"] }
  ]
}
```

Legacy clients may still see duplicate keys `gates`, `portal_graph`, and `via_portal` for backward compatibility. Edges include both `via_scanner` and `via_portal` (same gate id).

## Full response shape

```json
{
  "schema_version": 1,
  "event_id": "test_fest",
  "event_name": "Test Fest",
  "map_url": "/static/maps/test_fest_map.png",
  "coordinate_system": {
    "space": "normalized",
    "origin": "top_left",
    "x_range": [0.0, 1.0],
    "y_range": [0.0, 1.0],
    "navmesh_width": 400,
    "navmesh_height": 225
  },
  "barriers": [],
  "zones": [],
  "scanners": [],
  "calibration_anchors": [],
  "navmesh": { "encoding": "base64", "width": 400, "height": 225, "walkable_value": 0, "blocked_value": 1, "data": "..." },
  "scanner_graph": { "nodes": [], "edges": [] },
  "generated_at": "2026-06-16T12:00:00Z"
}
```

## Related endpoints

Sim also uses:

| Endpoint | Purpose |
|----------|---------|
| `GET /events` | Event picker |
| `GET /events/{event_id}` | Event metadata + `map_url` |
| Map image at `map_url` | Background texture (prepend server base URL) |

## Versioning

- `schema_version: 1` — current
- Clients must reject unknown major versions

## Errors

| Status | Meaning |
|--------|---------|
| 404 | Unknown `event_id` |
