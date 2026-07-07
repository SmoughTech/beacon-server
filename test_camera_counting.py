"""Tests for camera-count reconciliation (gate ledger vs density cross-check)."""

from camera_counting import normalize_kind, reconcile_counts


def _gate(sid, cin, cout, zone=None):
    return {"source_id": sid, "name": sid, "zone_id": zone, "cumulative_in": cin, "cumulative_out": cout}


def _density(sid, heads, zone=None):
    return {"source_id": sid, "name": sid, "zone_id": zone, "heads": heads}


def test_normalize_kind():
    assert normalize_kind("gate") == "gate"
    assert normalize_kind("DENSITY") == "density"
    assert normalize_kind("bogus") == "density"
    assert normalize_kind(None) == "density"


def test_ledger_sums_across_gates():
    summary = reconcile_counts(
        [_gate("g1", 1200, 40), _gate("g2", 800, 10)],
        [],
    )
    assert summary["total_in"] == 2000
    assert summary["total_out"] == 50
    assert summary["occupancy_ledger"] == 1950
    assert summary["headline_total"] == 1950
    assert summary["has_density"] is False
    assert summary["density_observed"] is None
    assert summary["divergence"]["absolute"] is None


def test_density_cross_check_and_divergence():
    summary = reconcile_counts(
        [_gate("g1", 1000, 0)],
        [_density("d1", 900), _density("d2", 150)],
    )
    assert summary["density_observed"] == 1050
    assert summary["divergence"]["absolute"] == 50  # 1050 observed - 1000 ledger
    assert summary["divergence"]["pct"] == 5.0


def test_divergence_pct_none_when_ledger_zero():
    summary = reconcile_counts([], [_density("d1", 300)])
    assert summary["occupancy_ledger"] == 0
    assert summary["density_observed"] == 300
    assert summary["divergence"]["absolute"] == 300
    assert summary["divergence"]["pct"] is None


def test_per_zone_rollup_groups_unzoned():
    summary = reconcile_counts(
        [],
        [
            _density("d1", 100, zone="zone_a"),
            _density("d2", 50, zone="zone_a"),
            _density("d3", 25),  # unzoned
        ],
    )
    by_zone = {row["zone_id"]: row["density_heads"] for row in summary["per_zone"]}
    assert by_zone["zone_a"] == 150
    assert by_zone[None] == 25


def test_negative_ledger_is_preserved():
    # More recorded exits than entries (e.g. counter drift) -> negative, surfaced not hidden.
    summary = reconcile_counts([_gate("g1", 10, 40)], [])
    assert summary["occupancy_ledger"] == -30
