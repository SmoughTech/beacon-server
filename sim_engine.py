"""Token flow processor — access layout is the machine; spawned guests are tokens."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from access_control import normalize_path_flow_direction, normalize_zone_class
from tile_grid import TILE_COLS, TILE_ROWS, grid_from_norm, norm_from_grid

SIM_TICK_HZ = 30
SCAN_TIME_TICKS = 45  # 1.5 s at 30 Hz — visible queue + scan feedback
PATH_STEP_EVERY_TICKS = 6  # ~5 path tiles/sec
QUEUE_STEP_EVERY_TICKS = 5  # ~6 queue tiles/sec
DIRS = ((0, -1), (1, 0), (0, 1), (-1, 0))


class TokenStage(str, Enum):
    ON_PATH = "on_path"
    IN_QUEUE = "in_queue"
    SCANNING = "scanning"


@dataclass
class PathTrack:
    path_id: str
    tiles: list[tuple[int, int]]
    flow: str

    @classmethod
    def from_dict(cls, path: dict[str, Any]) -> PathTrack:
        raw = path.get("tiles") or []
        tiles = [(int(t[0]), int(t[1])) for t in raw if isinstance(t, (list, tuple)) and len(t) >= 2]
        flow = normalize_path_flow_direction(path.get("flow_direction") or path.get("flowDirection"))
        return cls(path_id=path["id"], tiles=tiles, flow=flow)

    def clamp_index(self, index: int) -> int:
        if not self.tiles:
            return 0
        return max(0, min(index, len(self.tiles) - 1))

    def tile_at(self, index: int) -> tuple[int, int] | None:
        if not self.tiles:
            return None
        return self.tiles[self.clamp_index(index)]

    def downstream_end_index(self) -> int:
        if not self.tiles:
            return 0
        return len(self.tiles) - 1 if self.flow == "forward" else 0

    def at_downstream_end(self, index: int) -> bool:
        return index == self.downstream_end_index()

    def next_index(self, index: int) -> int | None:
        if self.flow == "forward":
            nxt = index + 1
            return nxt if nxt < len(self.tiles) else None
        nxt = index - 1
        return nxt if nxt >= 0 else None


@dataclass
class Token:
    id: int
    ticket_class: str
    path_id: str
    path_index: int
    tx: int
    ty: int
    stage: TokenStage = TokenStage.ON_PATH
    target_gate_id: str | None = None
    target_zone_id: str | None = None
    spawn_point_id: str | None = None
    scan_timer: int = 0
    queue_index: int | None = None
    step_cooldown: int = 0


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
    if not points:
        return []
    from tile_grid import tile_from_norm

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
    zone_a = gate.get("zone_a_id")
    zone_b = gate.get("zone_b_id")
    if not zone_a and not zone_b:
        return True
    return target_zone_id in (zone_a, zone_b)


class TokenFlowEngine:
    def __init__(
        self,
        event_id: str,
        zones: list[dict[str, Any]],
        gates: list[dict[str, Any]],
        paths: list[dict[str, Any]],
        spawn_points: list[dict[str, Any]],
        queue_polylines: list[dict[str, Any]],
    ) -> None:
        self.event_id = event_id
        self.zones = zones
        self.gates = gates
        self.spawn_points = spawn_points
        self.paths_by_id = {p["id"]: PathTrack.from_dict(p) for p in paths}
        self.queues_by_gate: dict[str, list[tuple[int, int]]] = {}
        for q in queue_polylines:
            gid = q.get("gate_id")
            if gid:
                tiles = _rasterize_queue(q.get("points") or [])
                if tiles:
                    self.queues_by_gate[gid] = tiles

        self.tokens: list[Token] = []
        self.next_token_id = 1
        self.tick = 0
        self.spawn_interval = 15
        self.spawn_plan: list[str] = []
        self.spawn_cursor = 0
        self.spawn_cooldown = 0
        self.stats = {"spawned": 0, "scanned": 0, "active": 0}
        self.warnings: list[str] = []
        self._spawn_point_cursor = 0
        self.gate_flash: dict[str, int] = {}

    def configure_spawns(self, ga_count: int, vip_count: int, spawn_interval: int) -> None:
        self.spawn_interval = spawn_interval
        self.spawn_plan = ["ga"] * ga_count + ["vip"] * vip_count
        self.spawn_cursor = 0
        self.spawn_cooldown = 0
        self._spawn_point_cursor = 0
        self.warnings = []

    def reset(self, ga_count: int = 20, vip_count: int = 0, spawn_interval: int = 15) -> None:
        self.tokens.clear()
        self.next_token_id = 1
        self.tick = 0
        self.stats = {"spawned": 0, "scanned": 0, "active": 0}
        self.gate_flash = {}
        self.configure_spawns(ga_count, vip_count, spawn_interval)
        self.warnings = self.diagnostics()
        if self.spawn_plan:
            if self.spawn_one(self.spawn_plan[0]):
                self.spawn_cursor = 1
                self.spawn_cooldown = spawn_interval
            elif not self.warnings:
                self.warnings.append("Could not spawn token — add spawn points on paths.")

    def diagnostics(self) -> list[str]:
        warnings: list[str] = []
        if not self.zones:
            warnings.append("No zones — use Fill Zone in Access Control.")
        if not self.gates:
            warnings.append("No scanners placed.")
        if not self.spawn_points:
            warnings.append("No spawn points — use Place Spawn on a painted path.")
        elif not self.paths_by_id:
            warnings.append("No paths — draw paths before placing spawn points.")
        if self.gates and not self.queues_by_gate:
            warnings.append("No queue lines — draw queues from path entrance to each scanner.")
        return warnings

    def zone_for_class(self, ticket_class: str) -> dict[str, Any] | None:
        tc = ticket_class.strip().lower()
        for zone in self.zones:
            zc = (zone.get("zone_class") or "ga").strip().lower()
            if zc == tc:
                return zone
        return self.zones[0] if self.zones else None

    def pick_gate(
        self,
        ticket_class: str,
        target_zone_id: str | None,
        from_tx: int,
        from_ty: int,
        path_id: str | None = None,
    ) -> dict[str, Any] | None:
        start = (from_tx, from_ty)
        path_end: tuple[int, int] | None = None
        if path_id:
            track = self.paths_by_id.get(path_id)
            if track and track.tiles:
                path_end = track.tile_at(track.downstream_end_index())

        candidates = [g for g in self.gates if _gate_admits(g, ticket_class, target_zone_id)]
        with_queue = [g for g in candidates if g["id"] in self.queues_by_gate]
        ordered = with_queue + [g for g in candidates if g not in with_queue]

        best: tuple[int, dict[str, Any]] | None = None
        for gate in ordered:
            score = 10**9
            queue = self.queue_tiles(gate["id"])
            if path_end and queue:
                score = _manhattan(path_end, queue[0])
            else:
                gx, gy = grid_from_norm(float(gate["map_x"]), float(gate["map_y"]))
                score = _manhattan(start, (gx, gy))
            if best is None or score < best[0]:
                best = (score, gate)
        return best[1] if best else None

    def spawn_points_for_class(self, ticket_class: str) -> list[dict[str, Any]]:
        tc = ticket_class.strip().lower()
        matched = [sp for sp in self.spawn_points if (sp.get("ticket_class") or "ga").strip().lower() == tc]
        return matched or self.spawn_points

    def spawn_one(self, ticket_class: str) -> bool:
        zone = self.zone_for_class(ticket_class)
        if not zone:
            return False
        candidates = self.spawn_points_for_class(ticket_class)
        if not candidates:
            return False

        for _ in range(len(candidates)):
            sp = candidates[self._spawn_point_cursor % len(candidates)]
            self._spawn_point_cursor += 1
            track = self.paths_by_id.get(sp["path_id"])
            if not track or not track.tiles:
                continue
            idx = track.clamp_index(int(sp.get("tile_index", 0)))
            tile = track.tile_at(idx)
            if not tile:
                continue
            if any(t.path_id == sp["path_id"] and t.path_index == idx and t.stage == TokenStage.ON_PATH for t in self.tokens):
                continue

            gate = self.pick_gate(ticket_class, zone["id"], tile[0], tile[1], sp["path_id"])
            token = Token(
                id=self.next_token_id,
                ticket_class=ticket_class,
                path_id=sp["path_id"],
                path_index=idx,
                tx=tile[0],
                ty=tile[1],
                target_gate_id=gate["id"] if gate else None,
                target_zone_id=zone["id"],
                spawn_point_id=sp["id"],
            )
            self.tokens.append(token)
            self.next_token_id += 1
            self.stats["spawned"] += 1
            self.stats["active"] = len(self.tokens)
            return True
        return False

    def queue_tiles(self, gate_id: str | None) -> list[tuple[int, int]]:
        if not gate_id:
            return []
        return self.queues_by_gate.get(gate_id) or []

    def queue_head_tile(self, gate_id: str) -> tuple[int, int] | None:
        """Legacy alias — scan happens at queue_scan_tile (furthest point from tail)."""
        return self.queue_scan_tile(gate_id)

    def queue_scan_index(self, gate_id: str) -> int:
        tiles = self.queue_tiles(gate_id)
        if len(tiles) <= 1:
            return 0
        tail = tiles[0]
        best_i = len(tiles) - 1
        best_d = _manhattan(tail, tiles[-1])
        for i, tile in enumerate(tiles):
            dist = _manhattan(tail, tile)
            if dist > best_d:
                best_d = dist
                best_i = i
        if best_i == 0:
            best_i = len(tiles) - 1
        return best_i

    def queue_scan_tile(self, gate_id: str) -> tuple[int, int] | None:
        tiles = self.queue_tiles(gate_id)
        if not tiles:
            gate = next((g for g in self.gates if g["id"] == gate_id), None)
            if not gate:
                return None
            return grid_from_norm(float(gate["map_x"]), float(gate["map_y"]))
        return tiles[self.queue_scan_index(gate_id)]

    def queue_tail_tile(self, gate_id: str) -> tuple[int, int] | None:
        tiles = self.queue_tiles(gate_id)
        if tiles:
            return tiles[0]
        return self.queue_head_tile(gate_id)

    def token_at(self, tx: int, ty: int) -> Token | None:
        for token in self.tokens:
            if token.tx == tx and token.ty == ty:
                return token
        return None

    def queue_index_taken(self, gate_id: str, index: int, except_id: int) -> bool:
        for token in self.tokens:
            if token.id == except_id or token.target_gate_id != gate_id:
                continue
            if token.stage not in (TokenStage.IN_QUEUE, TokenStage.SCANNING):
                continue
            if token.queue_index == index:
                return True
        return False

    def on_queue_head(self, token: Token) -> bool:
        if not token.target_gate_id:
            return False
        tiles = self.queue_tiles(token.target_gate_id)
        if not tiles:
            head = self.queue_scan_tile(token.target_gate_id)
            return head is not None and (token.tx, token.ty) == head
        scan_idx = self.queue_scan_index(token.target_gate_id)
        if token.queue_index is None or token.queue_index < scan_idx:
            return False
        return (token.tx, token.ty) == tiles[scan_idx]

    def greedy_step_toward(
        self,
        token: Token,
        goal: tuple[int, int],
        occupied_check: Callable[[int, int], bool],
    ) -> bool:
        pos = (token.tx, token.ty)
        if pos == goal:
            return False
        best: tuple[int, int] | None = None
        best_score = 10**9
        for dx, dy in DIRS:
            nx, ny = token.tx + dx, token.ty + dy
            if occupied_check(nx, ny):
                continue
            score = _manhattan((nx, ny), goal)
            if score < best_score:
                best_score = score
                best = (nx, ny)
        if best is None or best == pos:
            return False
        token.tx, token.ty = best
        return True

    def path_tile_taken(self, path_id: str, index: int, except_id: int) -> bool:
        for token in self.tokens:
            if token.id == except_id or token.stage != TokenStage.ON_PATH:
                continue
            if token.path_id == path_id and token.path_index == index:
                return True
        return False

    def queue_tile_taken(self, tx: int, ty: int, except_id: int) -> bool:
        for token in self.tokens:
            if token.id == except_id:
                continue
            if token.stage in (TokenStage.IN_QUEUE, TokenStage.SCANNING) and token.tx == tx and token.ty == ty:
                return True
        return False

    def _is_adjacent(self, a: tuple[int, int], b: tuple[int, int]) -> bool:
        return _manhattan(a, b) == 1

    def _tile_blocked(self, tx: int, ty: int, except_id: int) -> bool:
        for token in self.tokens:
            if token.id == except_id:
                continue
            if token.tx == tx and token.ty == ty:
                return True
        return False

    def _nearest_queue_gate(self, token: Token, max_dist: int = 12) -> str | None:
        pos = (token.tx, token.ty)
        best_gate: str | None = None
        best_dist = max_dist + 1
        for gate_id, tiles in self.queues_by_gate.items():
            if not tiles:
                continue
            gate = next((g for g in self.gates if g["id"] == gate_id), None)
            if not gate or not _gate_admits(gate, token.ticket_class, token.target_zone_id):
                continue
            dist = _manhattan(pos, tiles[0])
            if dist < best_dist:
                best_dist = dist
                best_gate = gate_id
        return best_gate

    def _resolve_gate_for_queue(self, token: Token) -> str | None:
        if token.target_gate_id and self.queue_tiles(token.target_gate_id):
            return token.target_gate_id
        gate_id = self._nearest_queue_gate(token, max_dist=25) or token.target_gate_id
        if not gate_id or not self.queue_tiles(gate_id):
            return None
        return gate_id

    def _claim_queue_index(
        self,
        token: Token,
        gate_id: str,
        index: int,
        snap_to: tuple[int, int] | None = None,
    ) -> bool:
        tiles = self.queue_tiles(gate_id)
        if not tiles or index < 0 or index >= len(tiles):
            return False
        if self.queue_index_taken(gate_id, index, token.id):
            return False
        token.target_gate_id = gate_id
        if snap_to is not None:
            token.tx, token.ty = snap_to
        elif (token.tx, token.ty) != tiles[index]:
            token.tx, token.ty = tiles[index]
        self.enter_queue(token)
        token.queue_index = index
        token.step_cooldown = QUEUE_STEP_EVERY_TICKS - 1
        return True

    def _queue_index_near(self, gate_id: str, tx: int, ty: int, max_dist: int = 2) -> int | None:
        tiles = self.queue_tiles(gate_id)
        best_i: int | None = None
        best_d = max_dist + 1
        for i, (qx, qy) in enumerate(tiles):
            d = _manhattan((tx, ty), (qx, qy))
            if d <= max_dist and d < best_d:
                best_d = d
                best_i = i
        return best_i

    def _path_junction_index(self, track: PathTrack, gate_id: str) -> int | None:
        """Path tile index closest to the queue tail (T-junction)."""
        tiles = self.queue_tiles(gate_id)
        if not tiles or not track.tiles:
            return None
        tail = tiles[0]
        max_dist = 4
        best_i: int | None = None
        best_d = max_dist + 1
        downstream = track.downstream_end_index()
        for i, pt in enumerate(track.tiles):
            d = _manhattan(pt, tail)
            if d > max_dist:
                continue
            if best_i is None or d < best_d or (d == best_d and abs(i - downstream) < abs(best_i - downstream)):
                best_i = i
                best_d = d
        return best_i

    def _try_transition_path_to_queue(self, token: Token) -> bool:
        gate_id = self._resolve_gate_for_queue(token)
        if not gate_id:
            gate_id = self._nearest_queue_gate(token, max_dist=30)
        if not gate_id:
            return False
        tiles = self.queue_tiles(gate_id)
        if not tiles:
            return False

        pos = (token.tx, token.ty)
        scan_idx = self.queue_scan_index(gate_id)
        track = self.paths_by_id.get(token.path_id)
        tail = tiles[0]

        q_idx = self._queue_index_near(gate_id, pos[0], pos[1], max_dist=3)
        if q_idx is not None and q_idx <= scan_idx:
            return self._claim_queue_index(token, gate_id, q_idx)

        if track:
            junction_pi = self._path_junction_index(track, gate_id)
            if junction_pi is not None and token.path_index >= junction_pi:
                return self._claim_queue_index(token, gate_id, 0, snap_to=tail)

            nxt_idx = track.next_index(token.path_index)
            if nxt_idx is not None:
                nxt_tile = track.tile_at(nxt_idx)
                if nxt_tile:
                    nxt_q = self._queue_index_near(gate_id, nxt_tile[0], nxt_tile[1], max_dist=3)
                    if nxt_q is not None and nxt_q <= scan_idx:
                        if self.queue_index_taken(gate_id, nxt_q, token.id):
                            return False
                        token.path_index = nxt_idx
                        token.tx, token.ty = nxt_tile
                        return self._claim_queue_index(token, gate_id, nxt_q)

        at_path_end = bool(track and track.at_downstream_end(token.path_index))
        near_tail = _manhattan(pos, tail) <= 10
        if at_path_end or near_tail:
            return self._claim_queue_index(token, gate_id, 0, snap_to=tail)

        return False

    def _try_join_queue_from_path(self, token: Token) -> bool:
        """Alias used by tests and legacy callers."""
        return self._try_transition_path_to_queue(token)

    def enter_queue(self, token: Token) -> None:
        if token.stage == TokenStage.IN_QUEUE:
            return
        token.stage = TokenStage.IN_QUEUE
        token.queue_index = None
        token.step_cooldown = 0

    def _start_scan(self, token: Token) -> None:
        token.stage = TokenStage.SCANNING
        token.scan_timer = SCAN_TIME_TICKS
        if token.target_gate_id:
            self.gate_flash[token.target_gate_id] = SCAN_TIME_TICKS
            scan_tile = self.queue_scan_tile(token.target_gate_id)
            if scan_tile:
                token.tx, token.ty = scan_tile

    def _finish_scan(self, token: Token) -> None:
        self.tokens = [t for t in self.tokens if t.id != token.id]
        self.stats["scanned"] += 1
        self.stats["active"] = len(self.tokens)

    def _tick_gate_flash(self) -> None:
        expired: list[str] = []
        for gate_id, remaining in self.gate_flash.items():
            self.gate_flash[gate_id] = remaining - 1
            if self.gate_flash[gate_id] <= 0:
                expired.append(gate_id)
        for gate_id in expired:
            del self.gate_flash[gate_id]

    def _advance_queue(self, token: Token) -> None:
        if token.step_cooldown > 0:
            token.step_cooldown -= 1
            return

        gate_id = token.target_gate_id
        if not gate_id:
            return

        tiles = self.queue_tiles(gate_id)
        if not tiles:
            return

        scan_idx = self.queue_scan_index(gate_id)

        if self.on_queue_head(token):
            self._start_scan(token)
            return

        if token.queue_index is None:
            if self._try_transition_path_to_queue(token):
                return
            return

        if token.queue_index >= scan_idx:
            if (token.tx, token.ty) == tiles[scan_idx]:
                self._start_scan(token)
            return

        next_idx = token.queue_index + 1
        if next_idx > scan_idx:
            return
        if self.queue_index_taken(gate_id, next_idx, token.id):
            return
        token.queue_index = next_idx
        token.tx, token.ty = tiles[next_idx]
        token.step_cooldown = QUEUE_STEP_EVERY_TICKS - 1

    def advance_token(self, token: Token) -> None:
        if token.stage == TokenStage.SCANNING:
            token.scan_timer -= 1
            if token.scan_timer <= 0:
                self._finish_scan(token)
            return

        if token.stage == TokenStage.IN_QUEUE:
            self._advance_queue(token)
            return

        if token.step_cooldown > 0:
            token.step_cooldown -= 1
            return

        if self._try_transition_path_to_queue(token):
            return

        track = self.paths_by_id.get(token.path_id)
        if not track:
            return

        if track.at_downstream_end(token.path_index):
            return

        nxt_idx = track.next_index(token.path_index)
        if nxt_idx is None:
            return
        if self.path_tile_taken(token.path_id, nxt_idx, token.id):
            return
        nxt_tile = track.tile_at(nxt_idx)
        if not nxt_tile:
            return
        token.path_index = nxt_idx
        token.tx, token.ty = nxt_tile
        token.step_cooldown = PATH_STEP_EVERY_TICKS - 1

    def tick_once(self) -> None:
        self.tick += 1
        self._tick_gate_flash()
        if self.spawn_cursor < len(self.spawn_plan):
            self.spawn_cooldown -= 1
            if self.spawn_cooldown <= 0:
                if self.spawn_one(self.spawn_plan[self.spawn_cursor]):
                    self.spawn_cursor += 1
                self.spawn_cooldown = self.spawn_interval

        for token in list(self.tokens):
            self.advance_token(token)

        self.stats["active"] = len(self.tokens)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "tick": self.tick,
            "stats": self.stats,
            "warnings": getattr(self, "warnings", []),
            "spawn_remaining": max(0, len(self.spawn_plan) - self.spawn_cursor),
            "scanner_activity": [
                {
                    "gate_id": gate_id,
                    "remaining_ticks": remaining,
                    "progress": min(1.0, remaining / SCAN_TIME_TICKS),
                }
                for gate_id, remaining in self.gate_flash.items()
            ],
            "agents": [
                {
                    "id": t.id,
                    "ticket_class": t.ticket_class,
                    "tx": t.tx,
                    "ty": t.ty,
                    "state": t.stage.value,
                    "path_id": t.path_id,
                    "path_index": t.path_index,
                    "queue_index": t.queue_index,
                    "gate_id": t.target_gate_id,
                    "scan_timer": t.scan_timer if t.stage == TokenStage.SCANNING else 0,
                    "scan_progress": (
                        1.0 - (t.scan_timer / SCAN_TIME_TICKS)
                        if t.stage == TokenStage.SCANNING
                        else None
                    ),
                }
                for t in self.tokens
            ],
        }


_engines: dict[str, TokenFlowEngine] = {}


def _load_engine(
    event_id: str,
    get_connection: Callable,
    zone_row_to_dict: Callable,
    scanner_gate_row_to_dict: Callable,
    queue_row_to_dict: Callable,
    path_row_to_dict: Callable,
    spawn_point_row_to_dict: Callable,
) -> TokenFlowEngine:
    with get_connection() as conn:
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
        paths = [
            path_row_to_dict(r)
            for r in conn.execute(
                "SELECT * FROM access_paths WHERE event_id = ? ORDER BY name COLLATE NOCASE",
                (event_id,),
            ).fetchall()
        ]
        spawn_points = [
            spawn_point_row_to_dict(r)
            for r in conn.execute(
                "SELECT * FROM access_spawn_points WHERE event_id = ? ORDER BY name COLLATE NOCASE",
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
    return TokenFlowEngine(event_id, zones, gates, paths, spawn_points, queues)


def register_sim_engine(
    app,
    get_connection: Callable,
    get_event_config: Callable,
    barrier_row_to_dict: Callable,
    zone_row_to_dict: Callable,
    scanner_gate_row_to_dict: Callable,
    queue_row_to_dict: Callable,
    path_row_to_dict: Callable,
    spawn_point_row_to_dict: Callable | None = None,
) -> None:
    if spawn_point_row_to_dict is None:
        from access_control import spawn_point_row_to_dict as _spawn_row

        spawn_point_row_to_dict = _spawn_row

    router = APIRouter()

    def _ensure(event_id: str) -> TokenFlowEngine:
        try:
            get_event_config(event_id)
        except Exception as exc:
            raise HTTPException(status_code=404, detail="Event not found") from exc
        if event_id not in _engines:
            _engines[event_id] = _load_engine(
                event_id,
                get_connection,
                zone_row_to_dict,
                scanner_gate_row_to_dict,
                queue_row_to_dict,
                path_row_to_dict,
                spawn_point_row_to_dict,
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

    @router.post("/events/{event_id}/sim/stop")
    def sim_stop(event_id: str):
        try:
            get_event_config(event_id)
        except Exception as exc:
            raise HTTPException(status_code=404, detail="Event not found") from exc
        _engines.pop(event_id, None)
        return {
            "event_id": event_id,
            "stopped": True,
            "tick": 0,
            "stats": {"spawned": 0, "scanned": 0, "active": 0},
            "agents": [],
            "spawn_remaining": 0,
            "warnings": [],
            "scanner_activity": [],
        }

    @router.get("/events/{event_id}/sim/state")
    def sim_state(event_id: str):
        engine = _engines.get(event_id)
        if not engine:
            return {"event_id": event_id, "tick": 0, "stats": {}, "agents": []}
        return engine.to_dict()

    app.include_router(router)
