"""Tile-native crowd sim — one guest per 2ft cell, path-preferring movement."""

from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from geometry import (
    SURFACE_AREA,
    SURFACE_BLOCKED,
    SURFACE_PATH,
    build_surface_grid,
    point_in_polygon,
    rasterize_walls,
)
from tile_grid import TILE_COLS, TILE_ROWS, grid_from_norm, norm_from_grid, tile_from_norm

SIM_TICK_HZ = 30
SCAN_TIME_TICKS = 45  # 1.5 s
OFF_PATH_STEP_COST = 10
MAX_PATHFIND_EXPLORE = 8_000
MAX_PATHFIND_JOBS_PER_TICK = 4
MAX_AREA_CANDIDATES = 2_000
DIRS = ((0, -1), (1, 0), (0, 1), (-1, 0))

class AgentState(str, Enum):
    WALKING = "walking"
    QUEUING = "queuing"
    SCANNING = "scanning"
    IDLE = "idle"


@dataclass
class SimAgent:
    id: int
    ticket_class: str
    tx: int
    ty: int
    state: AgentState = AgentState.WALKING
    target_zone_id: str | None = None
    target_gate_id: str | None = None
    route: list[tuple[int, int]] = field(default_factory=list)
    goal: tuple[int, int] | None = None
    scan_timer: int = 0
    idle_tile: tuple[int, int] | None = None


class SimResetRequest(BaseModel):
    ga_count: int = Field(default=20, ge=0, le=500)
    vip_count: int = Field(default=0, ge=0, le=200)
    spawn_interval_ticks: int = Field(default=15, ge=1, le=600)


class SimTickRequest(BaseModel):
    steps: int = Field(default=1, ge=1, le=30)


def _bresenham_tiles(x0: int, y0: int, x1: int, y1: int) -> list[tuple[int, int]]:
    tiles: list[tuple[int, int]] = []
    dx = abs(x1 - x0)
    dy = abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx - dy
    while True:
        tiles.append((x0, y0))
        if x0 == x1 and y0 == y1:
            break
        e2 = 2 * err
        if e2 > -dy:
            err -= dy
            x0 += sx
        if e2 < dx:
            err += dx
            y0 += sy
    return tiles


def _rasterize_queue(points: list[dict[str, Any]]) -> list[tuple[int, int]]:
    """Tail → head tile order (first drawn point = back of line)."""
    if not points:
        return []
    out: list[tuple[int, int]] = []
    seen: set[tuple[int, int]] = set()
    for i in range(len(points) - 1):
        ax, ay = tile_from_norm(float(points[i]["x"]), float(points[i]["y"]))
        bx, by = tile_from_norm(float(points[i + 1]["x"]), float(points[i + 1]["y"]))
        for tx, ty in _bresenham_tiles(ax, ay, bx, by):
            if (tx, ty) not in seen:
                seen.add((tx, ty))
                out.append((tx, ty))
    if len(points) == 1:
        tx, ty = tile_from_norm(float(points[0]["x"]), float(points[0]["y"]))
        out.append((tx, ty))
    return out


def _manhattan(a: tuple[int, int], b: tuple[int, int]) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def _gate_admits(gate: dict[str, Any], ticket_class: str, target_zone_id: str | None) -> bool:
    allowed = gate.get("allowed_classes") or []
    if allowed and ticket_class not in allowed:
        return False
    if not target_zone_id:
        return True
    return target_zone_id in (gate.get("zone_a_id"), gate.get("zone_b_id"))


class CrowdSimEngine:
    def __init__(
        self,
        event_id: str,
        barriers: list[dict[str, Any]],
        zones: list[dict[str, Any]],
        gates: list[dict[str, Any]],
        queue_polylines: list[dict[str, Any]],
        paths: list[dict[str, Any]],
    ) -> None:
        self.event_id = event_id
        self.zones = zones
        self.gates = gates
        self.zones_by_id = {z["id"]: z for z in zones}
        self.queues_by_gate: dict[str, list[tuple[int, int]]] = {}
        for q in queue_polylines:
            gid = q.get("gate_id")
            if gid:
                self.queues_by_gate[gid] = _rasterize_queue(q.get("points") or [])

        wall = rasterize_walls(barriers, gates)
        self.blocked = [[wall[gy][gx] == 1 for gx in range(TILE_COLS)] for gy in range(TILE_ROWS)]
        self.surface = build_surface_grid(barriers, gates, zones, paths)

        self.agents: list[SimAgent] = []
        self.next_agent_id = 1
        self.tick = 0
        self.spawn_interval = 15
        self.spawn_plan: list[str] = []
        self.spawn_cursor = 0
        self.spawn_cooldown = 0
        self.stats = {"spawned": 0, "scanned": 0, "idle": 0}
        self.warnings: list[str] = []

        self._spawn_tiles = self._collect_spawn_tiles()
        self._area_tiles_by_zone = self._index_area_tiles()

    def _collect_spawn_tiles(self) -> list[tuple[int, int]]:
        tiles: list[tuple[int, int]] = []
        for ty in range(TILE_ROWS):
            for tx in range(TILE_COLS):
                if self.blocked[ty][tx] or self.surface[ty][tx] == SURFACE_BLOCKED:
                    continue
                if self.surface[ty][tx] == SURFACE_AREA:
                    continue
                tiles.append((tx, ty))
        return tiles or [(0, TILE_ROWS - 1)]

    def _index_area_tiles(self) -> dict[str, list[tuple[int, int]]]:
        indexed: dict[str, list[tuple[int, int]]] = {}
        for zone in self.zones:
            zone_id = zone["id"]
            polygon = zone.get("polygon") or []
            if len(polygon) < 3:
                indexed[zone_id] = []
                continue
            min_tx, max_tx = TILE_COLS - 1, 0
            min_ty, max_ty = TILE_ROWS - 1, 0
            for p in polygon:
                tx, ty = tile_from_norm(float(p["x"]), float(p["y"]))
                min_tx = min(min_tx, tx)
                max_tx = max(max_tx, tx)
                min_ty = min(min_ty, ty)
                max_ty = max(max_ty, ty)
            tiles: list[tuple[int, int]] = []
            for ty in range(max(0, min_ty), min(TILE_ROWS, max_ty + 1)):
                for tx in range(max(0, min_tx), min(TILE_COLS, max_tx + 1)):
                    if self.surface[ty][tx] != SURFACE_AREA:
                        continue
                    if not self.passable(tx, ty):
                        continue
                    cx, cy = norm_from_grid(tx, ty)
                    if point_in_polygon(cx, cy, polygon):
                        tiles.append((tx, ty))
            indexed[zone_id] = tiles
        return indexed

    def configure_spawns(self, ga_count: int, vip_count: int, spawn_interval: int) -> None:
        self.spawn_interval = spawn_interval
        self.spawn_plan = ["ga"] * ga_count + ["vip"] * vip_count
        self.spawn_cursor = 0
        self.spawn_cooldown = 0
        self.warnings: list[str] = []

    def reset(self, ga_count: int = 20, vip_count: int = 0, spawn_interval: int = 15) -> None:
        self.agents.clear()
        self.next_agent_id = 1
        self.tick = 0
        self.stats = {"spawned": 0, "scanned": 0, "idle": 0}
        self.configure_spawns(ga_count, vip_count, spawn_interval)
        self.warnings = self.spawn_diagnostics()
        if self.spawn_plan:
            if self.spawn_one(self.spawn_plan[0]):
                self.spawn_cursor = 1
                self.spawn_cooldown = spawn_interval
            elif not self.warnings:
                self.warnings.append("Could not spawn guest — check zones and walkable area.")

    def passable(self, tx: int, ty: int) -> bool:
        if tx < 0 or ty < 0 or tx >= TILE_COLS or ty >= TILE_ROWS:
            return False
        if self.blocked[ty][tx]:
            return False
        return self.surface[ty][tx] != SURFACE_BLOCKED

    def occupancy(self, except_id: int | None = None) -> dict[tuple[int, int], int]:
        occ: dict[tuple[int, int], int] = {}
        for agent in self.agents:
            if agent.id == except_id:
                continue
            occ[(agent.tx, agent.ty)] = agent.id
        return occ

    def tile_free(self, tx: int, ty: int, occ: dict[tuple[int, int], int], agent_id: int) -> bool:
        holder = occ.get((tx, ty))
        return holder is None or holder == agent_id

    def step_cost(self, tx: int, ty: int) -> int:
        if self.surface[ty][tx] == SURFACE_PATH:
            return 1
        return OFF_PATH_STEP_COST

    def find_path(
        self,
        start: tuple[int, int],
        goal: tuple[int, int],
        agent_id: int,
    ) -> list[tuple[int, int]]:
        if start == goal:
            return []
        occ = self.occupancy(except_id=agent_id)
        came_from: dict[tuple[int, int], tuple[int, int] | None] = {start: None}
        cost_so_far: dict[tuple[int, int], int] = {start: 0}
        heap: list[tuple[int, int, int]] = [(0, start[0], start[1])]
        explored = 0

        while heap:
            if explored >= MAX_PATHFIND_EXPLORE:
                return []
            _, cx, cy = heapq.heappop(heap)
            current = (cx, cy)
            explored += 1
            if current == goal:
                break
            base_cost = cost_so_far[current]
            for dx, dy in DIRS:
                nx, ny = cx + dx, cy + dy
                nxt = (nx, ny)
                if not self.passable(nx, ny):
                    continue
                if not self.tile_free(nx, ny, occ, agent_id) and nxt != goal:
                    continue
                new_cost = base_cost + self.step_cost(nx, ny)
                old = cost_so_far.get(nxt)
                if old is not None and new_cost >= old:
                    continue
                cost_so_far[nxt] = new_cost
                priority = new_cost + _manhattan(nxt, goal)
                heapq.heappush(heap, (priority, nx, ny))
                came_from[nxt] = current

        if goal not in came_from:
            return []
        path: list[tuple[int, int]] = []
        cur: tuple[int, int] | None = goal
        while cur is not None and cur != start:
            path.append(cur)
            cur = came_from.get(cur)
        path.reverse()
        return path

    def zone_for_class(self, ticket_class: str) -> dict[str, Any] | None:
        tc = ticket_class.strip().lower()
        for zone in self.zones:
            zc = (zone.get("zone_class") or "ga").strip().lower()
            if zc == tc:
                return zone
        return self.zones[0] if self.zones else None

    def spawn_diagnostics(self) -> list[str]:
        warnings: list[str] = []
        if not self.zones:
            warnings.append("No zones — use Fill Zone in Access Control.")
        if not self.gates:
            warnings.append("No scanners placed.")
        if not self._spawn_tiles:
            warnings.append("No walkable spawn tiles outside zones.")
        return warnings

    def pick_gate(self, ticket_class: str, target_zone_id: str | None, from_tx: int, from_ty: int) -> dict[str, Any] | None:
        best: tuple[int, dict[str, Any]] | None = None
        start = (from_tx, from_ty)
        for gate in self.gates:
            if not _gate_admits(gate, ticket_class, target_zone_id):
                continue
            gx, gy = grid_from_norm(float(gate["map_x"]), float(gate["map_y"]))
            goal = self.queue_goal_tile(gate["id"], gx, gy)
            dist = _manhattan(start, goal)
            if best is None or dist < best[0]:
                best = (dist, gate)
        return best[1] if best else None

    def queue_goal_tile(self, gate_id: str, gx: int, gy: int) -> tuple[int, int]:
        tiles = self.queues_by_gate.get(gate_id) or []
        if tiles:
            return tiles[0]  # tail — join back of line
        return gx, gy

    def queue_head_tile(self, gate_id: str, gx: int, gy: int) -> tuple[int, int]:
        tiles = self.queues_by_gate.get(gate_id) or []
        if tiles:
            return tiles[-1]
        return gx, gy

    def spawn_one(self, ticket_class: str) -> bool:
        zone = self.zone_for_class(ticket_class)
        if not zone:
            return False
        if not self._spawn_tiles:
            return False
        idx = (self.next_agent_id * 17) % len(self._spawn_tiles)
        tx, ty = self._spawn_tiles[idx]
        occ = self.occupancy()
        for _ in range(len(self._spawn_tiles)):
            if self.tile_free(tx, ty, occ, self.next_agent_id):
                break
            idx = (idx + 1) % len(self._spawn_tiles)
            tx, ty = self._spawn_tiles[idx]
        else:
            return False

        gate = self.pick_gate(ticket_class, zone["id"], tx, ty)
        gate_id = gate["id"] if gate else None
        goal = None
        if gate:
            gx, gy = grid_from_norm(float(gate["map_x"]), float(gate["map_y"]))
            goal = self.queue_goal_tile(gate_id, gx, gy)

        agent = SimAgent(
            id=self.next_agent_id,
            ticket_class=ticket_class,
            tx=tx,
            ty=ty,
            target_zone_id=zone["id"],
            target_gate_id=gate_id,
            goal=goal,
        )
        # Route is computed lazily on first tick — keeps /sim/reset fast.
        self.agents.append(agent)
        self.next_agent_id += 1
        self.stats["spawned"] += 1
        return True

    def pick_area_tile(self, zone_id: str, agent_id: int) -> tuple[int, int] | None:
        tiles = self._area_tiles_by_zone.get(zone_id) or []
        if not tiles:
            return None
        occ = self.occupancy(except_id=agent_id)
        candidates: list[tuple[int, int, int]] = []
        for tx, ty in tiles:
            if not self.tile_free(tx, ty, occ, agent_id):
                continue
            density = 1 if (tx, ty) in occ else 0
            candidates.append((density, tx, ty))
            if len(candidates) >= MAX_AREA_CANDIDATES:
                break
        if not candidates:
            return None
        candidates.sort(key=lambda item: (item[0], item[1], item[2]))
        low = candidates[0][0]
        lowest = [c for c in candidates if c[0] == low]
        pick = lowest[agent_id % len(lowest)]
        return pick[1], pick[2]

    def near_queue(self, agent: SimAgent) -> bool:
        if not agent.target_gate_id:
            return False
        tiles = self.queues_by_gate.get(agent.target_gate_id) or []
        if not tiles:
            return False
        return min(_manhattan((agent.tx, agent.ty), t) for t in tiles) <= 2

    def on_queue_head(self, agent: SimAgent) -> bool:
        if not agent.target_gate_id:
            return False
        gate = next((g for g in self.gates if g["id"] == agent.target_gate_id), None)
        if not gate:
            return False
        gx, gy = grid_from_norm(float(gate["map_x"]), float(gate["map_y"]))
        head = self.queue_head_tile(agent.target_gate_id, gx, gy)
        return _manhattan((agent.tx, agent.ty), head) <= 1

    def queue_step_toward_head(self, agent: SimAgent) -> tuple[int, int] | None:
        tiles = self.queues_by_gate.get(agent.target_gate_id or "") or []
        if not tiles:
            return None
        pos = (agent.tx, agent.ty)
        best_i = min(range(len(tiles)), key=lambda i: _manhattan(pos, tiles[i]))
        if best_i >= len(tiles) - 1:
            return tiles[-1]
        return tiles[best_i + 1]

    def try_move(self, agent: SimAgent, occ: dict[tuple[int, int], int]) -> None:
        if agent.state == AgentState.IDLE:
            return
        if agent.state == AgentState.SCANNING:
            agent.scan_timer -= 1
            if agent.scan_timer <= 0:
                agent.target_gate_id = None
                area = self.pick_area_tile(agent.target_zone_id or "", agent.id)
                if area:
                    agent.idle_tile = area
                    agent.goal = area
                    agent.route = self.find_path((agent.tx, agent.ty), area, agent.id)
                    agent.state = AgentState.WALKING
                else:
                    agent.state = AgentState.IDLE
                self.stats["scanned"] += 1
            return

        if agent.state == AgentState.QUEUING:
            if self.on_queue_head(agent):
                agent.state = AgentState.SCANNING
                agent.scan_timer = SCAN_TIME_TICKS
                agent.route = []
                return
            nxt = self.queue_step_toward_head(agent)
            if nxt and self.tile_free(nxt[0], nxt[1], occ, agent.id):
                agent.tx, agent.ty = nxt
            return

        # WALKING
        if agent.idle_tile and (agent.tx, agent.ty) == agent.idle_tile:
            agent.state = AgentState.IDLE
            self.stats["idle"] += 1
            agent.route = []
            return

        if agent.goal and (agent.tx, agent.ty) == agent.goal:
            if agent.target_gate_id:
                agent.state = AgentState.QUEUING
                agent.route = []
                return

        if agent.route:
            nxt = agent.route[0]
            if self.tile_free(nxt[0], nxt[1], occ, agent.id):
                agent.tx, agent.ty = nxt
                agent.route.pop(0)
                if self.near_queue(agent) and agent.target_gate_id:
                    agent.state = AgentState.QUEUING
                    agent.route = []
            return

        if agent.target_gate_id and self.near_queue(agent):
            agent.state = AgentState.QUEUING

    def tick_once(self) -> None:
        self.tick += 1
        if self.spawn_cursor < len(self.spawn_plan):
            self.spawn_cooldown -= 1
            if self.spawn_cooldown <= 0:
                if self.spawn_one(self.spawn_plan[self.spawn_cursor]):
                    self.spawn_cursor += 1
                self.spawn_cooldown = self.spawn_interval

        occ = self.occupancy()
        pathfind_jobs = 0
        for agent in self.agents:
            if (
                agent.state == AgentState.WALKING
                and agent.goal
                and not agent.route
                and (agent.tx, agent.ty) != agent.goal
                and pathfind_jobs < MAX_PATHFIND_JOBS_PER_TICK
            ):
                agent.route = self.find_path((agent.tx, agent.ty), agent.goal, agent.id)
                pathfind_jobs += 1
            self.try_move(agent, occ)
            occ = self.occupancy()

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "tick": self.tick,
            "stats": self.stats,
            "warnings": getattr(self, "warnings", []),
            "spawn_remaining": max(0, len(self.spawn_plan) - self.spawn_cursor),
            "agents": [
                {
                    "id": a.id,
                    "ticket_class": a.ticket_class,
                    "tx": a.tx,
                    "ty": a.ty,
                    "state": a.state.value,
                }
                for a in self.agents
            ],
        }


_engines: dict[str, CrowdSimEngine] = {}


def _load_engine(
    event_id: str,
    get_connection: Callable,
    barrier_row_to_dict: Callable,
    zone_row_to_dict: Callable,
    scanner_gate_row_to_dict: Callable,
    queue_row_to_dict: Callable,
    path_row_to_dict: Callable,
) -> CrowdSimEngine:
    with get_connection() as conn:
        barriers = [
            barrier_row_to_dict(r)
            for r in conn.execute(
                "SELECT * FROM access_barriers WHERE event_id = ? ORDER BY name COLLATE NOCASE",
                (event_id,),
            ).fetchall()
        ]
        zones = [
            zone_row_to_dict(r)
            for r in conn.execute(
                "SELECT * FROM access_zones WHERE event_id = ? ORDER BY name COLLATE NOCASE",
                (event_id,),
            ).fetchall()
        ]
        gates = [
            scanner_gate_row_to_dict(r)
            for r in conn.execute(
                "SELECT * FROM wrstops_gates WHERE event_id = ? ORDER BY name COLLATE NOCASE",
                (event_id,),
            ).fetchall()
        ]
        queues = [
            queue_row_to_dict(r)
            for r in conn.execute(
                "SELECT * FROM access_queue_polylines WHERE event_id = ? ORDER BY name COLLATE NOCASE",
                (event_id,),
            ).fetchall()
        ]
        paths = [
            path_row_to_dict(r)
            for r in conn.execute(
                "SELECT * FROM access_paths WHERE event_id = ? ORDER BY name COLLATE NOCASE",
                (event_id,),
            ).fetchall()
        ]
    return CrowdSimEngine(event_id, barriers, zones, gates, queues, paths)


def register_sim_engine(
    app,
    get_connection: Callable,
    get_event_config: Callable,
    barrier_row_to_dict: Callable,
    zone_row_to_dict: Callable,
    scanner_gate_row_to_dict: Callable,
    queue_row_to_dict: Callable,
    path_row_to_dict: Callable,
) -> None:
    router = APIRouter()

    def _ensure(event_id: str) -> CrowdSimEngine:
        try:
            get_event_config(event_id)
        except Exception as exc:
            raise HTTPException(status_code=404, detail="Event not found") from exc
        if event_id not in _engines:
            _engines[event_id] = _load_engine(
                event_id,
                get_connection,
                barrier_row_to_dict,
                zone_row_to_dict,
                scanner_gate_row_to_dict,
                queue_row_to_dict,
                path_row_to_dict,
            )
        return _engines[event_id]

    @router.post("/events/{event_id}/sim/reset")
    def sim_reset(event_id: str, payload: SimResetRequest):
        engine = _ensure(event_id)
        engine.reset(payload.ga_count, payload.vip_count, payload.spawn_interval_ticks)
        return engine.to_dict()

    @router.post("/events/{event_id}/sim/reload")
    def sim_reload(event_id: str):
        _engines.pop(event_id, None)
        engine = _ensure(event_id)
        engine.reset()
        return engine.to_dict()

    @router.post("/events/{event_id}/sim/tick")
    def sim_tick(event_id: str, payload: SimTickRequest):
        engine = _ensure(event_id)
        for _ in range(payload.steps):
            engine.tick_once()
        return engine.to_dict()

    @router.get("/events/{event_id}/sim/state")
    def sim_state(event_id: str):
        engine = _engines.get(event_id)
        if not engine:
            return {"event_id": event_id, "tick": 0, "stats": {}, "agents": []}
        return engine.to_dict()

    app.include_router(router)
