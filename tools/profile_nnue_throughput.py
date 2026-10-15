"""Detailed optional clocks/work counts, separate from release timing claims."""
from contextlib import ExitStack
import argparse
import json

from tools.nnue_diagnosis import BASE_OPTIONS, capture, metadata, open_engine, positions
from tools.nnue_throughput import ART, ROOT, build, save
from tools.profile_nnue_diagnosis import canonical


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strategy", default="compact")
    strategy = parser.parse_args().strategy
    builds = {"legacy_clocks": build("legacy-clocks", ["--nnue-update", "legacy", "--diagnostics", "--profile"]),
              "optimized_clocks": build("optimized-clocks", ["--nnue-update", strategy, "--diagnostics", "--profile"]),
              "optimized_counters": build("optimized-counters", ["--nnue-update", strategy, "--diagnostics"]),
              "release_baseline": ART / "baseline/engine.exe"}
    path = ROOT / "detailed-profile.json"
    data = json.loads(path.read_text()) if path.exists() else {
        "builds": {k: metadata(v) for k, v in builds.items()}, "records": [],
        "method": "One rotated pass of 24 FENs at 400k nodes. Clocks split delta construction, state extraction, feature metadata and row arithmetic, but every tiny scope perturbs timing. Counters describe work; fresh TT allocation is outside scopes. This is not release runtime attribution."}
    done = {(r["position"], r["build"]) for r in data["records"]}
    with ExitStack() as stack:
        engines = {k: stack.enter_context(open_engine(v)) for k, v in builds.items()}
        for engine in engines.values():
            engine.configure(BASE_OPTIONS | {"Evaluator": "nnue"})
        for i, row in enumerate(positions()):
            labels = list(engines)
            labels = labels[i % len(labels):] + labels[:i % len(labels)]
            for label in labels:
                if (row["id"], label) in done:
                    continue
                record = capture(engines[label], row, "nodes", 400000)
                data["records"].append(record | {"build": label})
            results = {r["build"]: r for r in data["records"] if r["position"] == row["id"]}
            assert all(canonical(r) == canonical(results["release_baseline"]) for r in results.values())
            for label in ("legacy_clocks", "optimized_clocks", "optimized_counters"):
                assert results[label]["diagnostics"]["delta_rows"] == results["legacy_clocks"]["diagnostics"]["delta_rows"]
                assert results[label]["diagnostics"]["updates"] == results["legacy_clocks"]["diagnostics"]["updates"]
            save(path, data)
            print("Detailed profile", row["id"], flush=True)


if __name__ == "__main__":
    main()
