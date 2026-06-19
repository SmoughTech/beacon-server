"""Tile-native crowd sim — one guest per 2ft cell, path-preferring movement."""

from __future__ import annotations

import heapq
from collections import deque
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
WALL_ADJACENCY_PENALTY = 8
MAX_PATHFIND_EXPLORE = 8_000
STUCK_REPLAN_TICKS = 20
MAX_PATHFIND_JOBS_PER_TICK = 4
MAX_AREA_CANDIDATES = 2_000
MIN_SPAWN_DIST_FROM_GATE = 40
SYNTHETIC_QUEUE_LENGTH = 16
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
    prev_tx: int | None = None
    prev_ty: int | None = None
    stuck_ticks: int = 0
    last_goal_dist: int = 0


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
    allowed = [str(c).strip().lower() for c in (gate.get("allowed_classes") or []) if c]
    tc = ticket_class.strip().lower()
    if allowed and tc not in allowed:
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
        self._painted_queue_gates: set[str] = set()
        for q in queue_polylines:
            gid = q.get("gate_id")
            if gid:
                tiles = _rasterize_queue(q.get("points") or [])
                if tiles:
                    self.queues_by_gate[gid] = tiles
                    self._painted_queue_gates.add(gid)

        wall = rasterize_walls(barriers, gates)
        self.blocked = [[wall[gy][gx] == 1 for gx in range(TILE_COLS)] for gy in range(TILE_ROWS)]
        self.surface = build_surface_grid(barriers, gates, zones, paths)

        for gid in list(self.queues_by_gate.keys()):
            normalized = self._normalize_queue_tiles(self.queues_by_gate[gid])
            if normalized:
                self.queues_by_gate[gid] = normalized
            else:
                self.queues_by_gate.pop(gid, None)

        self.layout_warnings: list[str] = []
        for gate in gates:
            gid = gate["id"]
            if self.queues_by_gate.get(gid):
                continue
            gx, gy = grid_from_norm(float(gate["map_x"]), float(gate["map_y"]))
            synthetic = self._synthetic_queue_for_gate(gx, gy)
            if synthetic:
                self.queues_by_gate[gid] = synthetic
                name = gate.get("name") or gid
                self.layout_warnings.append(
                    f'Scanner "{name}" has no queue line — sim uses an auto queue toward the scanner.'
                )

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

    def _gate_positions(self) -> list[tuple[int, int]]:
        positions: list[tuple[int, int]] = []
        for gate in self.gates:
            positions.append(grid_from_norm(float(gate["map_x"]), float(gate["map_y"])))
        return positions

    def _synthetic_queue_for_gate(self, gx: int, gy: int) -> list[tuple[int, int]]:
        """Tail → head line when no queue polyline was painted."""
        head = self.nearest_passable(gx, gy, max_radius=12)
        if not head:
            return []
        visited: dict[tuple[int, int], int] = {head: 0}
        queue: deque[tuple[tuple[int, int], int]] = deque([(head, 0)])
        best_tail = head
        best_score = (-1, 10**9)
        while queue:
            pos, dist = queue.popleft()
            if dist > SYNTHETIC_QUEUE_LENGTH:
                continue
            path_bias = 0 if self.surface[pos[1]][pos[0]] == SURFACE_PATH else 1
            score = (dist, -path_bias)
            if score > best_score:
                best_score = score
                best_tail = pos
            for dx, dy in DIRS:
                nxt = (pos[0] + dx, pos[1] + dy)
                if nxt in visited or not self.passable(nxt[0], nxt[1]):
                    continue
                visited[nxt] = dist + 1
                queue.append((nxt, dist + 1))
        if best_tail == head:
            for dx, dy in DIRS:
                nxt = (head[0] + dx, head[1] + dy)
                if self.passable(nxt[0], nxt[1]):
                    best_tail = nxt
                    break
        if best_tail == head:
            return [head]
        route = self.find_path(best_tail, head, agent_id=0)
        if route:
            return [best_tail, *route]
        return [best_tail, head]

    def _collect_spawn_tiles(self) -> list[tuple[int, int]]:
        gate_positions = self._gate_positions()

        def collect(min_dist: int) -> list[tuple[int, int]]:
            path_tiles: list[tuple[int, int]] = []
            walk_tiles: list[tuple[int, int]] = []
            for ty in range(TILE_ROWS):
                for tx in range(TILE_COLS):
                    if self.blocked[ty][tx] or self.surface[ty][tx] == SURFACE_BLOCKED:
                        continue
                    if self.surface[ty][tx] == SURFACE_AREA:
                        continue
                    if gate_positions:
                        nearest_gate = min(_manhattan((tx, ty), gp) for gp in gate_positions)
                        if nearest_gate < min_dist:
                            continue
                    if self.surface[ty][tx] == SURFACE_PATH:
                        path_tiles.append((tx, ty))
                    else:
                        walk_tiles.append((tx, ty))
            return path_tiles or walk_tiles

        for min_dist in (MIN_SPAWN_DIST_FROM_GATE, 30, 20, 0):
            tiles = collect(min_dist)
            if tiles:
                return tiles
        return [(TILE_COLS // 2, TILE_ROWS - 1)]

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

    def adjacent_wall_count(self, tx: int, ty: int) -> int:
        count = 0
        for dx, dy in DIRS:
            if not self.passable(tx + dx, ty + dy):
                count += 1
        return count

    def _normalize_queue_tiles(self, tiles: list[tuple[int, int]]) -> list[tuple[int, int]]:
        if not tiles:
            return []
        out: list[tuple[int, int]] = []
        for tx, ty in tiles:
            if not self.passable(tx, ty):
                alt = self.nearest_passable(tx, ty, max_radius=6, avoid_walls=True)
                if not alt:
                    continue
                tx, ty = alt
            if out and (tx, ty) == out[-1]:
                continue
            out.append((tx, ty))
        return out

    def step_cost(self, tx: int, ty: int) -> int:
        base = 1 if self.surface[ty][tx] == SURFACE_PATH else OFF_PATH_STEP_COST
        return base + self.adjacent_wall_count(tx, ty) * WALL_ADJACENCY_PENALTY

    def nearest_passable(
        self,
        tx: int,
        ty: int,
        max_radius: int = 16,
        *,
        avoid_walls: bool = False,
    ) -> tuple[int, int] | None:
        for radius in range(0, max_radius + 1):
            ring_best: tuple[int, int] | None = None
            ring_score = 10**9
            for dx in range(-radius, radius + 1):
                for dy in range(-radius, radius + 1):
                    if radius > 0 and max(abs(dx), abs(dy)) != radius:
                        continue
                    nx, ny = tx + dx, ty + dy
                    if not self.passable(nx, ny):
                        continue
                    score = radius * 100
                    if avoid_walls:
                        score += self.adjacent_wall_count(nx, ny) * 20
                    if self.surface[ny][nx] != SURFACE_PATH:
                        score += 15
                    if score < ring_score:
                        ring_score = score
                        ring_best = (nx, ny)
            if ring_best:
                return ring_best
        return None

    def resolve_goal(self, goal: tuple[int, int]) -> tuple[int, int]:
        resolved = self.nearest_passable(goal[0], goal[1], avoid_walls=True)
        return resolved if resolved else goal

    def resolve_goal_reachable(
        self,
        start: tuple[int, int],
        goal: tuple[int, int],
        agent_id: int,
    ) -> tuple[int, int]:
        resolved = self.resolve_goal(goal)
        if start == resolved:
            return resolved
        if self.find_path(start, resolved, agent_id):
            return resolved
        best: tuple[int, int] | None = None
        best_len = 10**9
        for radius in range(0, 25):
            for dx in range(-radius, radius + 1):
                for dy in range(-radius, radius + 1):
                    if radius > 0 and max(abs(dx), abs(dy)) != radius:
                        continue
                    nx, ny = resolved[0] + dx, resolved[1] + dy
                    if not self.passable(nx, ny):
                        continue
                    if self.adjacent_wall_count(nx, ny) >= 3:
                        continue
                    path = self.find_path(start, (nx, ny), agent_id)
                    if path and len(path) < best_len:
                        best_len = len(path)
                        best = (nx, ny)
            if best:
                return best
        return resolved

    def greedy_step_toward(
        self,
        agent: SimAgent,
        occ: dict[tuple[int, int], int],
    ) -> bool:
        if not agent.goal:
            return False
        pos = (agent.tx, agent.ty)
        if pos == agent.goal:
            return False
        prev = (
            (agent.prev_tx, agent.prev_ty)
            if agent.prev_tx is not None and agent.prev_ty is not None
            else None
        )
        ranked: list[tuple[int, tuple[int, int]]] = []
        for dx, dy in DIRS:
            nx, ny = agent.tx + dx, agent.ty + dy
            if not self.passable(nx, ny):
                continue
            if not self.tile_free(nx, ny, occ, agent.id):
                continue
            step = (nx, ny)
            score = _manhattan(step, agent.goal) + self.step_cost(nx, ny)
            ranked.append((score, step))
        if not ranked:
            return False
        ranked.sort(key=lambda item: item[0])
        best = ranked[0][1]
        if prev and best == prev and len(ranked) > 1:
            best = ranked[1][1]
        if best == pos:
            return False
        agent.tx, agent.ty = best
        return True

    def find_path(
        self,
        start: tuple[int, int],
        goal: tuple[int, int],
        agent_id: int,
    ) -> list[tuple[int, int]]:
        goal = self.resolve_goal(goal)
        if start == goal:
            return []
        start_dist = _manhattan(start, goal)
        occ = self.occupancy(except_id=agent_id)
        came_from: dict[tuple[int, int], tuple[int, int] | None] = {start: None}
        cost_so_far: dict[tuple[int, int], int] = {start: 0}
        heap: list[tuple[int, int, int]] = [(0, start[0], start[1])]
        explored = 0
        closest = start
        closest_dist = _manhattan(start, goal)

        while heap:
            if explored >= MAX_PATHFIND_EXPLORE:
                break
            _, cx, cy = heapq.heappop(heap)
            current = (cx, cy)
            explored += 1
            dist = _manhattan(current, goal)
            if dist < closest_dist:
                closest_dist = dist
                closest = current
            if current == goal:
                closest = goal
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

        if goal in came_from:
            target = goal
        elif closest_dist < start_dist:
            target = closest
            if self.adjacent_wall_count(closest[0], closest[1]) >= 2:
                path_cells = [
                    cell
                    for cell in cost_so_far
                    if cell != start and self.surface[cell[1]][cell[0]] == SURFACE_PATH
                ]
                if path_cells:
                    target = min(
                        path_cells,
                        key=lambda c: (
                            _manhattan(c, goal),
                            self.adjacent_wall_count(c[0], c[1]),
                        ),
                    )
        else:
            return []
        if target == start:
            return []
        path: list[tuple[int, int]] = []
        cur: tuple[int, int] | None = target
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
        warnings = list(getattr(self, "layout_warnings", []))
        if not self.zones:
            warnings.append("No zones — use Fill Zone in Access Control.")
        if not self.gates:
            warnings.append("No scanners placed.")
        elif not self._painted_queue_gates:
            warnings.append("No queue lines painted — draw back-of-line → scanner in Access Control.")
        if not self._spawn_tiles:
            warnings.append("No walkable spawn tiles outside zones.")
        return warnings

    def pick_gate(self, ticket_class: str, target_zone_id: str | None, from_tx: int, from_ty: int) -> dict[str, Any] | None:
        best: tuple[tuple[int, int], dict[str, Any]] | None = None
        start = (from_tx, from_ty)
        for gate in self.gates:
            if not _gate_admits(gate, ticket_class, target_zone_id):
                continue
            gx, gy = grid_from_norm(float(gate["map_x"]), float(gate["map_y"]))
            raw_goal = self.queue_goal_tile(gate["id"], gx, gy)
            goal = self.resolve_goal(raw_goal)
            path_len = len(self.find_path(start, goal, agent_id=0))
            if path_len == 0 and start != goal:
                continue
            metric = (path_len, _manhattan(start, goal))
            if best is None or metric < best[0]:
                best = (metric, gate)
        if best:
            return best[1]
        # Fallback: straight-line nearest if path routing failed for all gates.
        fallback: tuple[int, dict[str, Any]] | None = None
        for gate in self.gates:
            if not _gate_admits(gate, ticket_class, target_zone_id):
                continue
            gx, gy = grid_from_norm(float(gate["map_x"]), float(gate["map_y"]))
            goal = self.queue_goal_tile(gate["id"], gx, gy)
            dist = _manhattan(start, goal)
            if fallback is None or dist < fallback[0]:
                fallback = (dist, gate)
        return fallback[1] if fallback else None

    def queue_goal_tile(self, gate_id: str, gx: int, gy: int) -> tuple[int, int]:
        tiles = self.queues_by_gate.get(gate_id) or []
        if tiles:
            return tiles[0]  # tail — join back of line
        head = self.nearest_passable(gx, gy)
        return head if head else (gx, gy)

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
            raw_goal = self.queue_goal_tile(gate_id, gx, gy)
            goal = self.resolve_goal_reachable((tx, ty), raw_goal, self.next_agent_id)
        elif zone:
            goal = self._fallback_zone_goal(zone["id"], tx, ty)

        agent = SimAgent(
            id=self.next_agent_id,
            ticket_class=ticket_class,
            tx=tx,
            ty=ty,
            target_zone_id=zone["id"],
            target_gate_id=gate_id,
            goal=goal,
            last_goal_dist=_manhattan((tx, ty), goal) if goal else 0,
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

    def _fallback_zone_goal(self, zone_id: str, from_tx: int, from_ty: int) -> tuple[int, int] | None:
        tiles = self._area_tiles_by_zone.get(zone_id) or []
        if not tiles:
            return None
        best = min(tiles, key=lambda t: _manhattan((from_tx, from_ty), t))
        return self.resolve_goal(best)

    def at_queue_tail(self, agent: SimAgent) -> bool:
        if not agent.target_gate_id:
            return False
        tiles = self.queues_by_gate.get(agent.target_gate_id) or []
        if not tiles:
            return False
        tail = tiles[0]
        return _manhattan((agent.tx, agent.ty), tail) <= 2

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

    def _track_motion(self, agent: SimAgent) -> None:
        pos = (agent.tx, agent.ty)
        if agent.prev_tx is not None and agent.prev_ty is not None and (agent.prev_tx, agent.prev_ty) == pos:
            agent.stuck_ticks += 1
        elif agent.goal:
            dist = _manhattan(pos, agent.goal)
            if dist >= agent.last_goal_dist:
                agent.stuck_ticks += 1
            else:
                agent.stuck_ticks = max(0, agent.stuck_ticks - 1)
            agent.last_goal_dist = dist
        agent.prev_tx, agent.prev_ty = agent.tx, agent.ty

    def _unstick_agent(self, agent: SimAgent) -> None:
        if not agent.goal:
            return
        start = (agent.tx, agent.ty)
        agent.goal = self.resolve_goal_reachable(start, agent.goal, agent.id)
        agent.route = self.find_path(start, agent.goal, agent.id)
        agent.stuck_ticks = 0

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
                    agent.goal = self.resolve_goal_reachable((agent.tx, agent.ty), area, agent.id)
                    agent.last_goal_dist = _manhattan((agent.tx, agent.ty), agent.goal)
                    agent.route = self.find_path((agent.tx, agent.ty), agent.goal, agent.id)
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
                if self.at_queue_tail(agent) and agent.target_gate_id:
                    agent.state = AgentState.QUEUING
                    agent.route = []
            else:
                agent.route = self.find_path((agent.tx, agent.ty), agent.goal or (agent.tx, agent.ty), agent.id)
            self._track_motion(agent)
            return

        if agent.goal and (agent.tx, agent.ty) != agent.goal:
            if self.greedy_step_toward(agent, occ):
                agent.route = []
                self._track_motion(agent)
                return

        if agent.target_gate_id and self.at_queue_tail(agent):
            agent.state = AgentState.QUEUING

        if agent.state == AgentState.WALKING and agent.stuck_ticks >= STUCK_REPLAN_TICKS:
            self._unstick_agent(agent)

        self._track_motion(agent)

    def tick_once(self) -> None:
        self.tick += 1
        if self.spawn_cursor < len(self.spawn_plan):
            self.spawn_cooldown -= 1
            if self.spawn_cooldown <= 0:
                if self.spawn_one(self.spawn_plan[self.spawn_cursor]):
                    self.spawn_cursor += 1
                self.spawn_cooldown = self.spawn_interval

        occ = self.occupancy()
        for agent in self.agents:
            if (
                agent.state == AgentState.WALKING
                and agent.goal
                and not agent.route
                and (agent.tx, agent.ty) != agent.goal
            ):
                agent.route = self.find_path((agent.tx, agent.ty), agent.goal, agent.id)
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
