"""Tests for token flow processor."""

from sim_engine import PathTrack, TokenFlowEngine, TokenStage


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
    token.stage = TokenStage.SCANNING
    token.scan_timer = 1
    engine.advance_token(token)
    assert len(engine.tokens) == 0
    assert engine.stats["scanned"] == 1


def test_spawn_requires_spawn_point():
    engine = TokenFlowEngine("evt", [], [], [], [], [])
    assert engine.spawn_one("ga") is False
