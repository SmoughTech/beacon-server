# Sim-layout API

Beacon desktop sim loads event operational layouts via a single consolidated endpoint.

## Endpoint

```
GET /events/{event_id}/sim-layout
```

Returns JSON describing barriers, zones, portals, calibration anchors, precomputed navmesh, and portal graph.

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
- `1` = blocked (barrier or portal virtual wall)

Navmesh is computed server-side in [`geometry.py`](geometry.py) using the same rasterization rules as Dash [`access-control.js`](static/dash/access-control.js).

## Portal graph

Derived from `wrstops_gates` portal-access fields:

- **Nodes:** `outside`, each zone (`kind: zone`), each gate (`kind: portal`)
- **Edges:** zone-to-zone transitions via a portal, respecting `direction` and `allowed_classes`

```json
"portal_graph": {
  "nodes": [
    { "id": "outside", "kind": "outside", "label": "Outside" },
    { "id": "zone_abc", "kind": "zone", "label": "GA Lawn", "zone_class": "ga", "centroid": { "x": 0.5, "y": 0.6 } },
    { "id": "wrstops_xyz", "kind": "portal", "label": "Main Portal", "map_x": 0.42, "map_y": 0.55 }
  ],
  "edges": [
    { "from": "zone_ga", "to": "zone_vip", "via_portal": "wrstops_xyz", "allowed_classes": ["ga", "vip"] }
  ]
}
```

## Full response shape

```json
{
  "schema_version": 1,
  "event_id": "lib_2026",
  "event_name": "LIB 2026",
  "map_url": "/static/maps/lib_map.png",
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
  "gates": [],
  "calibration_anchors": [],
  "navmesh": { "encoding": "base64", "width": 400, "height": 225, "walkable_value": 0, "blocked_value": 1, "data": "..." },
  "portal_graph": { "nodes": [], "edges": [] },
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
