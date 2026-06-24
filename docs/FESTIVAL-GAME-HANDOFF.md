# Beacon Festival — Game/Sim Handoff Notes

Use this when starting a **new agent chat** for the festival simulator (the RCT-style game
that doubles as an ops/consulting tool). Companion to `SIM-AGENT-HANDOFF.md`.

---

## Repos

| Repo | Path | Role |
|------|------|------|
| **beacon-server** | `C:\Users\cdcno\Documents\GitHub\beacon-server` | **System of record** — maps, zones, access rules, scanners, paths, spawns, queues, incidents. Exports `SimLayout`. |
| **beacon-festival** | `C:\Users\cdcno\Documents\GitHub\beacon-festival` | **Game / sim core** — Unity 6 + DOTS, flow-field crowd sim, top-down/2.5D render. Consumes `SimLayout`. |
| **beacon-sim** | `C:\Users\cdcno\Documents\GitHub\beacon-sim` | Legacy Rust/egui desktop sim (~100 agents). Behavioral reference only. |

Sibling repos — not a monorepo.

---

## Decisions locked

- **Engine:** Unity 6 LTS + DOTS (Entities, Burst, Jobs).
- **View:** top-down / 2.5D.
- **System of record:** beacon-server stays authoritative; engine consumes its data.
- **First deliverable:** design doc + repo scaffold (done — see beacon-festival).

## Scale strategy (the 100k requirement)

Flow fields (Dijkstra distance field per goal, O(1) per-agent sampling) + ECS/Burst parallel
jobs + spatial-hash avoidance + simulation LOD (continuum crowd far / full agents near) +
GPU instanced rendering. Deterministic fixed 30 Hz core, decoupled from render FPS.

## Behavior parity

The festival sim's queue/scan/access logic must stay parity-tested against
`beacon-server/sim_engine.py` (path → queue → scan → admit; `_gate_admits`,
`_rasterize_queue`, `queue_scan_index`).

---

## Full design

`beacon-festival/docs/FESTIVAL-SIM-DESIGN.md` — architecture, ECS model, system order,
dual-use metrics, phased roadmap (Phase 0 → 5), risks, decision log.

## Current status

**Phase 0 scaffold complete:** repo, DOTS manifest, SimLayout DTOs + HTTP client (matches
beacon-server schema), ECS components, flow-field/movement/gate system skeletons, and
`SimBootstrap` (fetches bundle, bakes nav grid). **Phase 1 next:** wire flow fields, gates,
spawns; reach 100k agents @ 30 Hz.

## Partner (human, physical-world) tasks

Ground-truth calibration (real gate throughput via scanner hardware, walk speeds, queue
behavior), site surveys / map calibration, domain SOPs (incident + deployment), permit/AHJ
egress standards, and a pilot festival for Phase 5 validation.
