"""Tests for tile-native crowd sim."""

from sim_engine import AgentState, CrowdSimEngine, SimAgent, _bresenham_tiles, _rasterize_queue


def test_bresenham_straight_line():
    tiles = _bresenham_tiles(0, 0, 3, 0)
    assert tiles == [(0, 0), (1, 0), (2, 0), (3, 0)]


def test_rasterize_queue_two_points():
    pts = [{"x": 0.1, "y": 0.5}, {"x": 0.2, "y": 0.5}]
    tiles = _rasterize_queue(pts)
    assert len(tiles) >= 2
    assert tiles[0] != tiles[-1]


def test_engine_spawn_and_tick():
    zones = [
        {
            "id": "ga_lawn",
            "name": "GA",
            "zone_class": "ga",
            "polygon": [
                {"x": 0.55, "y": 0.35},
                {"x": 0.95, "y": 0.35},
                {"x": 0.95, "y": 0.95},
                {"x": 0.55, "y": 0.95},
            ],
        }
    ]
    gates = [
        {
            "id": "gate1",
            "map_x": 0.5,
            "map_y": 0.5,
            "zone_a_id": "outside",
            "zone_b_id": "ga_lawn",
            "allowed_classes": ["ga"],
        }
    ]
    engine = CrowdSimEngine("evt", [], zones, gates, [], [])
    engine.reset(ga_count=2, vip_count=0, spawn_interval=1)
    for _ in range(5):
        engine.tick_once()
    assert engine.stats["spawned"] >= 1
    assert all(a.tx >= 0 and a.ty >= 0 for a in engine.agents)


def test_occupancy_blocks_same_tile():
    engine = CrowdSimEngine("evt", [], [], [], [], [])
    engine.agents.append(
        SimAgent(id=1, ticket_class="ga", tx=10, ty=10, state=AgentState.WALKING)
    )
    engine.agents.append(
        SimAgent(id=2, ticket_class="ga", tx=11, ty=10, state=AgentState.WALKING)
    )
    occ = engine.occupancy()
    assert occ[(10, 10)] == 1
    assert occ[(11, 10)] == 2
    assert len(occ) == 2
