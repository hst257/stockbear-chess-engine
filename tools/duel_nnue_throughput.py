"""Direct paired candidate comparison, avoiding conclusions across separate runs."""
from contextlib import ExitStack
import argparse
import json
import math
import statistics

from tools.nnue_diagnosis import BASE_OPTIONS, capture, metadata, open_engine, positions, sha
from tools.nnue_throughput import ART, ROOT, save
from tools.profile_nnue_diagnosis import canonical
from tools.analyze_nnue_throughput import geometric, interval


def duel(first: str, second: str, evaluator: str = "nnue", repeats: int = 5) -> None:
    path = ROOT / f"duel-{first}-{second}-{evaluator}.json"
    builds = {name: ART / name / "engine.exe" for name in (first, second)}
    data = json.loads(path.read_text()) if path.exists() else {
        "builds": {name: metadata(binary) for name, binary in builds.items()}, "records": [],
        "method": "Direct serial alternating paired 400k-node trials; first/second wall speed ratio favors second when above one."}
    assert all(data["builds"][name]["sha256"] == sha(binary) for name, binary in builds.items())
    done = {(r["position"], r["repeat"], r["build"]) for r in data["records"]}
    with ExitStack() as stack:
        engines = {name: stack.enter_context(open_engine(binary)) for name, binary in builds.items()}
        for engine in engines.values():
            engine.configure(BASE_OPTIONS | {"Evaluator": evaluator})
        for repeat in range(repeats):
            for index, row in enumerate(positions()):
                for name in ((first, second) if (repeat + index) % 2 == 0 else (second, first)):
                    if (row["id"], repeat, name) in done:
                        continue
                    record = capture(engines[name], row, "nodes", 400000)
                    data["records"].append(record | {"build": name, "repeat": repeat})
                records = [r for r in data["records"] if (r["position"], r["repeat"]) == (row["id"], repeat)]
                assert canonical(records[0]) == canonical(records[1]), (row["id"], repeat)
                save(path, data)
            print("Direct duel", first, second, evaluator, repeat, flush=True)
    per = []
    for row in positions():
        records = {name: [r for r in data["records"] if r["position"] == row["id"] and r["build"] == name] for name in builds}
        eligible = not row["short_forced_fixture"] and all(r["nodes"] == 400000 and r["seconds"] >= .01 for rs in records.values() for r in rs)
        ratio = statistics.median(r["wall_seconds"] for r in records[first]) / statistics.median(r["wall_seconds"] for r in records[second])
        per.append({"position": row["id"], "eligible": eligible, "speed_ratio_first_over_second": ratio})
    values = [r["speed_ratio_first_over_second"] for r in per if r["eligible"]]
    data["summary"] = {"geomean_first_over_second": geometric(values), "position_bootstrap95": interval(values, True), "per_position": per}
    save(path, data)
    print(json.dumps(data["summary"], indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("first")
    parser.add_argument("second")
    parser.add_argument("--evaluator", choices=("nnue", "classical"), default="nnue")
    parser.add_argument("--repeats", type=int, default=5)
    args = parser.parse_args()
    duel(args.first, args.second, args.evaluator, args.repeats)
