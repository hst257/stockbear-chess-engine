"""Measure final accumulator work at every requested fixed-node budget."""
import json
from collections import Counter

from tools.nnue_diagnosis import BASE_OPTIONS, capture, metadata, open_engine, positions, sha
from tools.nnue_throughput import ART, ROOT, save
from tools.profile_nnue_diagnosis import canonical


def main() -> None:
    path = ROOT / "work-counters.json"
    data = json.loads(path.read_text()) if path.exists() else {
        "build": metadata(ART / "optimized-counters/engine.exe"), "records": [],
        "method": "One counter-only pass at 100k/400k/1M nodes. Compare each canonical tree to final release and each work count to the pre-edit counter build. Instrumented timing is not used for speed claims."}
    assert data["build"]["sha256"] == sha(ART / "optimized-counters/engine.exe")
    before = json.loads((ROOT / "initial-profile.json").read_text())["records"]
    release = json.loads((ROOT / "benchmark-final.json").read_text())["records"]
    done = {(r["position"], r["budget"]) for r in data["records"]}
    with open_engine(ART / "optimized-counters/engine.exe") as engine:
        engine.configure(BASE_OPTIONS | {"Evaluator": "nnue"})
        for row in positions():
            for budget in (100000, 400000, 1000000):
                if (row["id"], budget) in done:
                    continue
                result = capture(engine, row, "nodes", budget)
                reference = next(r for r in release if r["position"] == row["id"] and r["budget"] == budget and r["repeat"] == 0 and r["build"] == "final")
                original = next(r for r in before if r["position"] == row["id"] and r["budget"] == budget and r["repeat"] == 0 and r["build"] == "counters")
                assert canonical(result) == canonical(reference) == canonical(original)
                for key in ("updates", "copies", "delta_rows", "evaluation_calls", "refreshes", "visits", "qvisits"):
                    assert result["diagnostics"][key] == original["diagnostics"][key], (row["id"], budget, key)
                data["records"].append(result | {"baseline_copy_payload_bytes": original["diagnostics"]["copy_payload_bytes"]})
            save(path, data)
            print("Work counters", row["id"], flush=True)
    data["summary"] = []
    for budget in (100000, 400000, 1000000):
        rows = [r for r in data["records"] if r["budget"] == budget]
        counts = Counter()
        for r in rows:
            counts.update({k: v for k, v in r["diagnostics"].items() if isinstance(v, int)})
        data["summary"].append({"budget": budget, "searches": len(rows),
            **{key: counts[key] for key in ("visits", "evaluation_calls", "updates", "refreshes", "delta_rows", "copy_payload_bytes")},
            "baseline_copy_payload_bytes": sum(r["baseline_copy_payload_bytes"] for r in rows)})
    save(path, data)


if __name__ == "__main__":
    main()
