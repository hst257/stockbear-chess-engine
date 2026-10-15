"""Independent arithmetic and measurement-contract gates for search-only NNUE state."""
import json
import math
import os
from pathlib import Path
import subprocess

import pytest

from tools.analyze_nnue_throughput import geometric, summarize
from tools.nnue_throughput import MODEL, MODEL_SHA
from tools.nnue_diagnosis import sha


def test_frozen_v2_model_identity():
    assert sha(MODEL) == MODEL_SHA


def test_geometric_speedup_treats_reciprocal_changes_symmetrically():
    assert geometric([2, .5]) == pytest.approx(1)


def test_throughput_uses_per_tree_nps_and_separates_short_mates(tmp_path):
    records = []
    for position in ("opening", "endgame", "mate_net"):
        for repeat in range(3):
            for label, seconds, wall in (("baseline", .1, .11), ("test", .08, .09), ("classical", .06, .07)):
                records.append({"position": position, "build": label, "repeat": repeat, "mode": "nodes", "budget": 100000,
                                "nodes": 100000 if position != "mate_net" else 500,
                                "seconds": seconds, "wall_seconds": wall, "depth": 6, "cpu_seconds": seconds})
    path = tmp_path / "experiment.json"
    path.write_text(json.dumps({"records": records}))
    result = summarize(path)["summary"][0]
    assert result["eligible"] == 2
    assert result["geomean_wall_speedup"] == pytest.approx(.11 / .09)
    assert result["geomean_nps_speedup"] == pytest.approx(1.25)
    assert result["geomean_nps_baseline_classical"] == pytest.approx(.6)
    assert result["geomean_nps_optimized_classical"] == pytest.approx(.75)
    assert result["gap_closed_fraction"] == pytest.approx(.375)
    assert result["wall_speedup_position_bootstrap95"] == pytest.approx([.11 / .09] * 2)


def test_native_search_only_state_matches_full_reference_bitwise():
    binary = Path(os.environ.get("CHESSLAB_THROUGHPUT_MICRO", "artifacts/nnue-v2-throughput/compact/micro.exe"))
    if not binary.exists():
        pytest.skip("Build a throughput micro target or set CHESSLAB_THROUGHPUT_MICRO")
    result = json.loads(subprocess.check_output([str(binary.resolve()), "--verify-throughput", "scalar"], text=True, timeout=90))
    assert result["bitwise_exact"]
    assert result["transitions"] > 30000 and result["nulls"] > 25000


def test_human_amended_odd_match_requires_explicit_partial_pair_marker(tmp_path):
    from tools.verify_match_records import verify_record
    source = Path("docs/nnue-v2-throughput/validation-500ms.json")
    if not source.exists():
        pytest.skip("Frozen amended tournament evidence is not present")
    assert verify_record(source)["games"] == 35
    record = json.loads(source.read_text())
    assert record["incomplete_last_pair"] and record["summary"]["complete_pairs"] == 17
    target = tmp_path / "missing-marker.json"
    record["incomplete_last_pair"] = False
    target.write_text(json.dumps(record))
    target.with_suffix(".pgn").write_bytes(source.with_suffix(".pgn").read_bytes())
    with pytest.raises(AssertionError):
        verify_record(target)
