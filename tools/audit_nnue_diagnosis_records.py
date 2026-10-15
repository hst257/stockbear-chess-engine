"""Audit the amended schedule, effective options and frozen output completeness."""
from __future__ import annotations

from collections import Counter
import json
from pathlib import Path

from tools.nnue_diagnosis import ROOT, save, sha
from tools.verify_match_records import verify_record


def main() -> None:
    plan = json.loads((ROOT / "match-plan.json").read_text(encoding="utf-8"))
    book = json.loads(Path(plan["opening_book"]).read_text(encoding="utf-8"))
    assert sha(Path(plan["opening_book"])) == plan["opening_book_sha256"]
    assert sha(Path(plan["model"])) == plan["model_sha256"]
    assert sha(Path(plan["engine"])) == plan["engine_sha256"]
    report = {"tournaments": [], "position_experiments": {}, "planned_and_completed_games": 190}
    for scheduled in plan["schedule"]:
        path = Path(scheduled["output"])
        verified = verify_record(path, check_binaries=True)
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["requested_games"] == scheduled["games"]
        assert data["movetime_ms"] == scheduled["movetime"] and data["max_plies"] == scheduled["max_plies"]
        assert data["openings"] == book["openings"][:scheduled["games"] // 2]
        assert data["options"]["candidate"] == data["options"]["original"]
        assert data["options"]["candidate"]["Evaluator"] == "classical"
        overrides = data["overrides"]
        assert overrides["candidate"]["Evaluator"] == "nnue" and overrides["original"]["Evaluator"] == "classical"
        assert {k: v for k, v in overrides["candidate"].items() if k != "Evaluator"} == {k: v for k, v in overrides["original"].items() if k != "Evaluator"}
        assert overrides["candidate"]["NNUEKernel"] == "scalar" and overrides["candidate"]["Hash"] == 16
        for build in data["builds"].values():
            assert build["nnue"]["sha256"] == plan["model_sha256"]
        moves = [s for game in data["games"] for s in game["searches"]]
        assert all(s["wall_seconds"] > 0 and s["seconds"] >= 0 for s in moves)
        report["tournaments"].append(verified | {"movetime_ms": data["movetime_ms"],
            "nested_prefix_and_model_and_effective_options_verified": True,
            "searched_moves": len(moves), "zero_completed_depth_moves": sum(s["depth"] == 0 for s in moves),
            "wall_over_150_percent_requested_moves": sum(s["wall_seconds"] > data["movetime_ms"] / 1000 * 1.5 for s in moves),
            "maximum_wall_seconds": max(s["wall_seconds"] for s in moves),
            "terminations": dict(Counter(g["termination"] for g in data["games"]))})
    assert sum(r["games"] for r in report["tournaments"]) == 190
    for filename, expected in (("controlled-searches.json", 1296), ("ablations.json", 1152), ("accumulator-profile.json", 432)):
        data = json.loads((ROOT / filename).read_text(encoding="utf-8"))
        assert len(data["records"]) == expected, (filename, len(data["records"]))
        assert len({(r["position"], r.get("evaluator"), r.get("configuration"), r.get("build"), r["mode"], r["budget"], r["repeat"]) for r in data["records"]}) == expected
        report["position_experiments"][filename] = {"records": expected, "unique_search_keys": True, "sha256": sha(ROOT / filename)}
    reference = json.loads((ROOT / "stockfish-quality.json").read_text(encoding="utf-8"))
    assert len(reference["records"]) == 24
    report["stockfish"] = {"positions": 24, "distinct_candidate_child_analyses": sum(len(r["candidates"]) for r in reference["records"]), "metadata": reference["metadata"], "id": reference["engine_id"]}
    save(ROOT / "record-audit.json", report)
    print(json.dumps({"games": 190, "search_records": sum(v["records"] for v in report["position_experiments"].values()), "stockfish_candidate_analyses": report["stockfish"]["distinct_candidate_child_analyses"]}))


if __name__ == "__main__":
    main()
