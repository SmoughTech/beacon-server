"""Tests for token flow processor."""

from sim_engine import PathTrack, Token, TokenFlowEngine, TokenStage, _manhattan


def test_path_track_flow_forward():
    track = PathTrack("p1", [(0, 0), (1, 0), (2, 0)], "forward")
    assert track.next_index(0) == 1
    assert track.next_index(1) == 2
    assert track.next_index(2) is None
    assert track.at_downstream_end(2)


def test_path_track_flow_reverse():
    track = PathTrack("p1", [(0, 0), (1, 0), (2, 0)], "reverse")
    assert track.next_index(2) == 1
    assert track.at_downstream_end(0)


def test_token_deleted_after_scan():
    zones = [{"id": "ga", "zone_class": "ga", "polygon": []}]
    gates = [
        {
            "id": "g1",
            "map_x": 0.5,
            "map_y": 0.5,
            "allowed_classes": ["ga"],
            "zone_b_id": "ga",
        }
    ]
    paths = [
        {
            "id": "path1",
            "tiles": [[10, 10], [11, 10], [12, 10]],
            "flow_direction": "forward",
        }
    ]
    spawn_points = [
        {
            "id": "sp1",
            "path_id": "path1",
            "tile_index": 0,
            "map_x": 0.025,
            "map_y": 0.045,
            "ticket_class": "ga",
        }
    ]
    engine = TokenFlowEngine("evt", zones, gates, paths, spawn_points, [])
    engine.reset(ga_count=1, vip_count=0, spawn_interval=100)
    assert len(engine.tokens) == 1
    token = engine.tokens[0]
    engine._start_scan(token)
    assert engine.gate_flash.get("g1") == 45
    token.scan_timer = 1
    engine.advance_token(token)
    assert len(engine.tokens) == 0
    assert engine.stats["scanned"] == 1


def test_queue_waits_for_tail():
    zones = [{"id": "ga", "zone_class": "ga", "polygon": []}]
    gates = [{"id": "g1", "map_x": 0.5, "map_y": 0.5, "allowed_classes": ["ga"]}]
    paths = [{"id": "p1", "tiles": [[5, 5]], "flow_direction": "forward"}]
    spawns = [{"id": "s1", "path_id": "p1", "tile_index": 0, "map_x": 0.01, "map_y": 0.02, "ticket_class": "ga"}]
    queues = [{"gate_id": "g1", "points": [{"x": 0.1, "y": 0.2}, {"x": 0.12, "y": 0.2}]}]
    engine = TokenFlowEngine("evt", zones, gates, paths, spawns, queues)
    t1 = Token(id=1, ticket_class="ga", path_id="p1", path_index=0, tx=5, ty=5, stage=TokenStage.IN_QUEUE, target_gate_id="g1", queue_index=0)
    t1.tx, t1.ty = engine.queue_tiles("g1")[0]
    t2 = Token(id=2, ticket_class="ga", path_id="p1", path_index=0, tx=5, ty=5, stage=TokenStage.IN_QUEUE, target_gate_id="g1", queue_index=None)
    t2.tx, t2.ty = 5, 5
    engine.tokens = [t1, t2]
    engine._advance_queue(t2)
    assert t2.queue_index is None


def test_queue_does_not_scan_before_reaching_head():
    zones = [{"id": "ga", "zone_class": "ga", "polygon": []}]
    gate_x, gate_y = 0.52, 0.48
    gx, gy = 208, 108  # approx grid for gate
    gates = [{"id": "g1", "map_x": gate_x, "map_y": gate_y, "allowed_classes": ["ga"]}]
    paths = [{"id": "p1", "tiles": [[gx, gy], [gx + 1, gy]], "flow_direction": "forward"}]
    spawns = [{"id": "s1", "path_id": "p1", "tile_index": 0, "map_x": 0.01, "map_y": 0.02, "ticket_class": "ga"}]
    queues = [
        {
            "gate_id": "g1",
            "points": [
                {"x": (gx - 5) / 400, "y": gy / 225},
                {"x": (gx - 1) / 400, "y": gy / 225},
                {"x": gate_x, "y": gate_y},
            ],
        }
    ]
    engine = TokenFlowEngine("evt", zones, gates, paths, spawns, queues)
    token = Token(
        id=1,
        ticket_class="ga",
        path_id="p1",
        path_index=1,
        tx=gx + 1,
        ty=gy,
        stage=TokenStage.IN_QUEUE,
        target_gate_id="g1",
    )
    engine.tokens = [token]
    engine._advance_queue(token)
    assert token.stage == TokenStage.IN_QUEUE
    assert token.scan_timer == 0


def test_queue_scans_at_farthest_point_from_tail():
    zones = [{"id": "ga", "zone_class": "ga", "polygon": []}]
    gates = [{"id": "g1", "map_x": 0.1, "map_y": 0.2, "allowed_classes": ["ga"]}]
    paths = [{"id": "p1", "tiles": [[10, 10]], "flow_direction": "forward"}]
    spawns = [{"id": "s1", "path_id": "p1", "tile_index": 0, "map_x": 0.01, "map_y": 0.02, "ticket_class": "ga"}]
    queues = [
        {
            "gate_id": "g1",
            "points": [
                {"x": 0.1, "y": 0.2},
                {"x": 0.15, "y": 0.2},
                {"x": 0.15, "y": 0.25},
                {"x": 0.1, "y": 0.2},
            ],
        }
    ]
    engine = TokenFlowEngine("evt", zones, gates, paths, spawns, queues)
    tiles = engine.queue_tiles("g1")
    scan_idx = engine.queue_scan_index("g1")
    scan_tile = engine.queue_scan_tile("g1")
    assert scan_idx > 0
    assert scan_tile != tiles[0]
    assert _manhattan(scan_tile, tiles[0]) >= _manhattan(tiles[-1], tiles[0])


def test_no_scan_without_queue_line():
    zones = [{"id": "ga", "zone_class": "ga", "polygon": []}]
    gates = [{"id": "g1", "map_x": 0.5, "map_y": 0.5, "allowed_classes": ["ga"]}]
    paths = [{"id": "p1", "tiles": [[10, 10]], "flow_direction": "forward"}]
    spawns = [{"id": "s1", "path_id": "p1", "tile_index": 0, "map_x": 0.01, "map_y": 0.02, "ticket_class": "ga"}]
    engine = TokenFlowEngine("evt", zones, gates, paths, spawns, [])
    token = Token(
        id=1,
        ticket_class="ga",
        path_id="p1",
        path_index=0,
        tx=10,
        ty=10,
        stage=TokenStage.IN_QUEUE,
        target_gate_id="g1",
    )
    engine.tokens = [token]
    engine._advance_queue(token)
    assert token.stage == TokenStage.IN_QUEUE
    assert token.scan_timer == 0


def test_token_walks_queue_tiles_before_scan():
    zones = [{"id": "ga", "zone_class": "ga", "polygon": []}]
    gates = [{"id": "g1", "map_x": 0.75, "map_y": 0.5, "allowed_classes": ["ga"]}]
    paths = [{"id": "p1", "tiles": [[10, 10], [11, 10], [12, 10]], "flow_direction": "forward"}]
    spawns = [{"id": "s1", "path_id": "p1", "tile_index": 0, "map_x": 0.01, "map_y": 0.02, "ticket_class": "ga"}]
    queues = [
        {
            "gate_id": "g1",
            "points": [
                {"x": 12 / 400, "y": 10 / 225},
                {"x": 13 / 400, "y": 10 / 225},
                {"x": 14 / 400, "y": 10 / 225},
                {"x": 15 / 400, "y": 10 / 225},
            ],
        }
    ]
    engine = TokenFlowEngine("evt", zones, gates, paths, spawns, queues)
    token = Token(
        id=1,
        ticket_class="ga",
        path_id="p1",
        path_index=2,
        tx=12,
        ty=10,
        target_gate_id="g1",
    )
    engine.tokens = [token]
    engine._try_join_queue_from_path(token)
    assert token.stage == TokenStage.IN_QUEUE
    assert token.queue_index == 0
    for _ in range(3):
        token.step_cooldown = 0
        engine._advance_queue(token)
    assert token.stage == TokenStage.IN_QUEUE
    assert token.queue_index == 3
    token.step_cooldown = 0
    engine._advance_queue(token)
    assert token.stage == TokenStage.SCANNING


def test_handoff_at_path_junction_before_path_end():
    zones = [{"id": "ga", "zone_class": "ga", "polygon": []}]
    gates = [{"id": "g1", "map_x": 0.75, "map_y": 0.5, "allowed_classes": ["ga"]}]
    path_tiles = [(5, i) for i in range(10, 16)] + [(i, 15) for i in range(6, 16)]
    paths = [{"id": "p1", "tiles": path_tiles, "flow_direction": "forward"}]
    spawns = [{"id": "s1", "path_id": "p1", "tile_index": 0, "map_x": 0.01, "map_y": 0.02, "ticket_class": "ga"}]
    queues = [
        {
            "gate_id": "g1",
            "points": [
                {"x": 5 / 400, "y": 15 / 225},
                {"x": 10 / 400, "y": 15 / 225},
                {"x": 15 / 400, "y": 15 / 225},
            ],
        }
    ]
    engine = TokenFlowEngine("evt", zones, gates, paths, spawns, queues)
    junction_pi = engine._path_junction_index(PathTrack.from_dict(paths[0]), "g1")
    assert junction_pi is not None
    assert junction_pi < len(path_tiles) - 1
    token = Token(
        id=1,
        ticket_class="ga",
        path_id="p1",
        path_index=junction_pi,
        tx=5,
        ty=15,
        target_gate_id="g1",
    )
    engine.tokens = [token]
    assert engine._try_transition_path_to_queue(token)
    assert token.stage == TokenStage.IN_QUEUE
    assert token.queue_index == 0


def test_handoff_when_path_end_offset_from_queue_tail():
    """Path last tile can be a few cells off from rasterized queue tail (corner T)."""
    zones = [{"id": "ga", "zone_class": "ga", "polygon": []}]
    gates = [{"id": "g1", "map_x": 0.75, "map_y": 0.5, "allowed_classes": ["ga"]}]
    path_tiles = [(100, i) for i in range(50, 61)]
    paths = [{"id": "p1", "tiles": path_tiles, "flow_direction": "forward"}]
    spawns = [{"id": "s1", "path_id": "p1", "tile_index": 0, "map_x": 0.01, "map_y": 0.02, "ticket_class": "ga"}]
    queues = [
        {
            "gate_id": "g1",
            "points": [
                {"x": 105 / 400, "y": 60 / 225},
                {"x": 120 / 400, "y": 60 / 225},
            ],
        }
    ]
    engine = TokenFlowEngine("evt", zones, gates, paths, spawns, queues)
    token = Token(
        id=1,
        ticket_class="ga",
        path_id="p1",
        path_index=len(path_tiles) - 1,
        tx=100,
        ty=60,
        target_gate_id="g1",
    )
    engine.tokens = [token]
    assert engine._try_transition_path_to_queue(token)
    assert token.stage == TokenStage.IN_QUEUE
    assert token.queue_index == 0


def test_multiple_tokens_advance_through_queue():
    zones = [{"id": "ga", "zone_class": "ga", "polygon": []}]
    gates = [{"id": "g1", "map_x": 0.75, "map_y": 0.5, "allowed_classes": ["ga"]}]
    paths = [{"id": "p1", "tiles": [[10, 10], [11, 10], [12, 10]], "flow_direction": "forward"}]
    spawns = [{"id": "s1", "path_id": "p1", "tile_index": 0, "map_x": 0.01, "map_y": 0.02, "ticket_class": "ga"}]
    queues = [
        {
            "gate_id": "g1",
            "points": [
                {"x": 12 / 400, "y": 10 / 225},
                {"x": 13 / 400, "y": 10 / 225},
                {"x": 14 / 400, "y": 10 / 225},
                {"x": 15 / 400, "y": 10 / 225},
            ],
        }
    ]
    engine = TokenFlowEngine("evt", zones, gates, paths, spawns, queues)
    t1 = Token(id=1, ticket_class="ga", path_id="p1", path_index=2, tx=12, ty=10, target_gate_id="g1")
    t2 = Token(id=2, ticket_class="ga", path_id="p1", path_index=2, tx=11, ty=10, target_gate_id="g1")
    engine.tokens = [t1, t2]
    engine._try_join_queue_from_path(t1)
    assert t1.queue_index == 0
    engine._try_join_queue_from_path(t2)
    assert t2.stage == TokenStage.ON_PATH
    for _ in range(120):
        for token in list(engine.tokens):
            token.step_cooldown = 0
            engine.advance_token(token)
    assert engine.stats["scanned"] >= 1


def test_spawn_assigns_gate_without_zone_links():
    zones = [{"id": "ga", "zone_class": "ga", "polygon": []}]
    gates = [{"id": "g1", "map_x": 0.75, "map_y": 0.067, "allowed_classes": ["ga"]}]
    path_tiles = [(100, i) for i in range(50, 61)]
    paths = [{"id": "p1", "tiles": path_tiles, "flow_direction": "forward"}]
    spawns = [{"id": "s1", "path_id": "p1", "tile_index": 0, "map_x": 0.01, "map_y": 0.02, "ticket_class": "ga"}]
    queues = [
        {
            "gate_id": "g1",
            "points": [{"x": 100 / 400, "y": 60 / 225}, {"x": 120 / 400, "y": 60 / 225}],
        }
    ]
    engine = TokenFlowEngine("evt", zones, gates, paths, spawns, queues)
    engine.reset(ga_count=1, vip_count=0, spawn_interval=100)
    assert len(engine.tokens) == 1
    assert engine.tokens[0].target_gate_id == "g1"
    for _ in range(100):
        engine.tick_once()
        if engine.tokens and engine.tokens[0].stage == TokenStage.IN_QUEUE:
            break
    assert engine.tokens[0].stage == TokenStage.IN_QUEUE


def test_spawn_requires_spawn_point():
    engine = TokenFlowEngine("evt", [], [], [], [], [])
    assert engine.spawn_one("ga") is False
