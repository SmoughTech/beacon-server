# Beacon Sim — Agent Handoff Notes

Use this doc when starting a **new agent chat** for crowd sim / pathfinding work.  
Copy or `@docs/SIM-AGENT-HANDOFF.md` into the prompt.

---

## Repos

| Repo | Path | Role |
|------|------|------|
| **beacon-server** | `C:\Users\cdcno\Documents\GitHub\beacon-server` | Dash editor, sim-layout export, tile grid, barrier rasterization |
| **beacon-sim** | `C:\Users\cdcno\Documents\GitHub\beacon-sim` | Desktop Rust sim (egui), RCT-style peep nav, rendering |

Sibling repos — not a monorepo.

---

## Tile grid (canonical)

- **1 tile = 2ft × 2ft** → `400 × 225` nav cells (`tile_grid.py`)
- Vertices on tile corners; 4 triangles per tile (future navmesh upgrade)
- Norm coords: vertex `(vx, vy)` → `(vx/400, vy/225)`
- **Today:** navmesh is binary walkable/blocked from barrier tiles only

---

## What exists today

### beacon-server
- **Schema v2** sim-layout (`sim_layout.py`)
- **Tile-painted barricades** — drag-paint tiles in Dash (`static/dash/access-control.js`)
- **Queue polylines** — drawn on vertices, cyan in sim
- **Gates/scanners** — scanner flow heading, approach/inside standpoints computed at sim load
- `geometry.py` — `rasterize_walls()`, `navmesh_to_bytes()` (0=walkable, 1=blocked)
- Survey paths API exists (`survey_paths`) — could seed path painting later

### beacon-sim
- **RCT-style pathfinding** — `src/pathfinding/peep_nav.rs` (junction memory, bounded heuristic search)
- **Three movement layers** (fragile handoffs):
  1. Grid pathfind (`choose_next_cell`) when walking toward goal
  2. Queue follow mode (polyline pull + `follow_queue_step`) when near drawn queue
  3. Scanner scan queue (`try_join_scan_queue` → `Queued` → `Scanning` → `finish_scan`)
- **Fixed 30 Hz sim tick** (`SIM_DT`), decoupled from render FPS
- **Perf toggles** — heatmap/labels off by default; pathfind budget 15k tiles / 32 agents per tick
- **No tile occupancy / collision** yet (`ENABLE_AGENT_COLLISION = false`)

---

## Known bugs (partially fixed, may persist)

1. **Queue head / scan-in** — guests stuck before scanner when queue vertex sits on barrier boundary. Fix direction: `scan_join_point()` uses scanner **approach** standoff, not raw polyline end.
2. **Top-right approach** — guests path to queue tail instead of nearest queue point; bounce along walls from interpolate+snap. Fix direction: route to nearest polyline point, `try_step_toward` for grid steps (no per-step `snap_norm_to_walkable`).
3. **Post-scan wall riding** — `zone_interior_goal` now marches from entry toward zone centroid (not random angle from center).
4. **Performance at ~100 guests** — was laggy due to heatmap draw, FPS-tied sim, per-tick clones; largely mitigated, not RCT-scale yet.

**User has NOT asked for commits/PRs** unless explicitly requested.

---

## RCT vs our system (summary)

| RCT2 | Beacon-sim today |
|------|------------------|
| Path tiles = the world | Barrier raster + continuous (x,y) on grid |
| Pathfind only at junctions | Pathfind when `next_cell` empty (batched) |
| 1 peep per path tile (implicit) | No occupancy grid |
| Queue = path tiles | Queue = separate polyline overlay |
| Wide paths ignored for AI | Every walkable cell can be a junction |
| Thousands of guests | ~100 before perf issues |

See conversation for full comparison. **User direction:** move toward RCT model.

---

## Agreed next architecture (user proposal — NOT implemented)

**Paint explicit paths and areas; 1 sim per 2ft tile.**

### Surface types per cell
| Type | Behavior |
|------|----------|
| `blocked` | Barriers |
| `path` | Preferred movement; **1 guest per tile** |
| `area` | Walkable grounds; guests fill/spread here |
| `queue` | Rasterized queue corridor → scanner |

### Path widths
- Paint **1 / 2 / 4 tiles wide** (= 2ft / 4ft / 8ft)
- Wide paths: walk along corridor without junction search; pick free lane across width

### Movement rules
- Guests **prefer path tiles**; if off-path → subgoal = nearest path tile
- **Tile-native position** `(tx, ty)` — render can lerp, logic is discrete
- **Occupancy grid**: target occupied → wait or pick alternate lane (pseudo-collision)

### Phased rollout
1. **Phase 1 (server):** surface enum in export + Dash paint path (1/2/4) + paint area in zones
2. **Phase 2 (sim):** tile-native agents, occupancy, nearest-path subgoal
3. **Phase 3:** area fill / density goals inside authorized zones
4. **Phase 4:** rasterize queues to path tiles; drop polyline follow mode

---

## Key files

### beacon-server
| File | Purpose |
|------|---------|
| `tile_grid.py` | 400×225 grid, norm ↔ tile conversions |
| `geometry.py` | Wall rasterization, navmesh bytes |
| `sim_layout.py` | Layout export schema |
| `access_control.py` | Barriers, queue polylines DB |
| `static/dash/access-control.js` | Map editor (barriers, queues, placement) |

### beacon-sim
| File | Purpose |
|------|---------|
| `src/pathfinding/peep_nav.rs` | RCT-style `choose_next_cell` |
| `src/pathfinding/mod.rs` | `NavGrid`, walkability |
| `src/sim/mod.rs` | Agents, scanners, queues, movement, perf |
| `src/render/mod.rs` | Map, agents, heatmap, overlays |
| `src/app.rs` | UI, fixed sim tick loop |
| `src/layout/mod.rs` | SimLayout deserialization |

---

## Constants (beacon-sim `sim/mod.rs`)

- `SIM_TICK_HZ = 30`, `SIM_DT = 1/30`
- `QUEUE_CORRIDOR_DIST`, `QUEUE_HEAD_JOIN_DIST`, `GATE_SCAN_JOIN_DIST`
- `PATHFIND_TILES_PER_TICK = 15000`, `PATHFIND_AGENTS_PER_TICK = 32`

---

## Suggested first message for new agent

```
Read @docs/SIM-AGENT-HANDOFF.md in beacon-server.

Implement Phase 1: add path/area surface types to sim-layout export and 
Dash path painting (1/2/4 tile brush). Do not change sim movement yet.

Repos:
- beacon-server: C:\Users\cdcno\Documents\GitHub\beacon-server
- beacon-sim: C:\Users\cdcno\Documents\GitHub\beacon-sim
```

Adjust the task line to whatever you want to tackle next.

---

## Transcript

Full prior chat:  
`C:\Users\cdcno\.cursor\projects\c-Users-cdcno-Documents-GitHub-beacon-server\agent-transcripts\29f0778e-d54a-4cf5-85ce-d8bb70212a09\29f0778e-d54a-4cf5-85ce-d8bb70212a09.jsonl`

Search keywords: `queue follow`, `scan_join_point`, `peep_nav`, `walkable_near_queue`, `PerfToggles`, `zone_interior_goal`.
