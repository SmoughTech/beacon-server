# Beacon Access Control (Dash UI)

## Files to deploy to GitHub / Render

Copy these into your [beacon-server](https://github.com/SmoughTech/beacon-server) repo:

```
beacon-server/
├── main.py                          ← use main_patched_beacon_server_v31_dash_freedom_default.py (renamed)
├── access_control.py                ← new
├── static/
│   └── dash/
│       └── access-control.js        ← new
```

## Deploy steps

1. Copy `access_control.py` and `static/dash/access-control.js` into your repo.
2. Replace `main.py` with the updated patched file from Downloads (or merge the marked changes).
3. Commit and push to `main` — Render will redeploy.
4. Open **Beacon Dash → Access Control** tab.

## Dash workflow

1. **Draw Barrier** — click map points along fences/barricades, then **Finish Barrier**.
2. **Fill Zone** — close an area with barriers, pick GA/VIP/Staff, click inside the enclosed area.
3. **Access Rules** — select a scanner, set Zone A → Zone B, allowed classes, save.

## API endpoints added

- `GET/POST /events/{id}/access-barriers`
- `PUT/DELETE /events/{id}/access-barriers/{barrier_id}`
- `GET/POST /events/{id}/access-zones`
- `PUT/DELETE /events/{id}/access-zones/{zone_id}`
- `PUT /events/{id}/scanners/{gate_id}/access`
- `GET /events/{id}/sim-layout` — consolidated layout + navmesh for desktop sim (see [docs/SIM-LAYOUT-API.md](docs/SIM-LAYOUT-API.md))
