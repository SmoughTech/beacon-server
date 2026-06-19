"""Tests for token flow processor."""

from sim_engine import PathTrack, Token, TokenFlowEngine, TokenStage


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
    assert engine.gate_flash.get("g1") == 90
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


def test_spawn_requires_spawn_point():
    engine = TokenFlowEngine("evt", [], [], [], [], [])
    assert engine.spawn_one("ga") is False
