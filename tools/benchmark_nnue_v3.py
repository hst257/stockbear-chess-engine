"""Serial rotated v3/v2/classical measurements with immutable resumable inputs."""
from __future__ import annotations

import argparse
from collections import defaultdict
from contextlib import ExitStack
import csv
import json
import math
from pathlib import Path
import random
import statistics

from tools.nnue_diagnosis import BASE_OPTIONS, capture, metadata, open_engine, positions, sha
from tools.nnue_throughput import process_cpu
from tools.match_optimizations import write_record

ROOT = Path("docs/nnue-v3")
MODEL = Path("engine/networks/v3/stockbear-v3-selected.sbnnue")
BUILDS = {"classical": Path("artifacts/nnue-v3/classical/engine.exe"),
          "v2": Path("artifacts/nnue-v3/v2/engine.exe"),
          "v3": Path("artifacts/nnue-v3/release/engine.exe")}


def geometric(values) -> float:
    return math.exp(statistics.mean(math.log(v) for v in values))


def interval(values: list[float]) -> list[float]:
    rng = random.Random(20261016)
    samples = sorted(geometric(rng.choices(values, k=len(values))) for _ in range(10000))
    return [samples[250], samples[9749]]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    path = ROOT / "benchmark.json"
    signature = {"builds": {k: sha(v) for k, v in BUILDS.items()}, "model_sha256": sha(MODEL),
                 "repeats": args.repeats, "nodes": [100000, 400000, 1000000], "time_ms": [50, 200, 500, 1000],
                 "options": BASE_OPTIONS}
    data = json.loads(path.read_text()) if path.exists() else {
        "signature": signature, "metadata": {k: metadata(v) for k, v in BUILDS.items()}, "records": [],
        "method": "Three rotated serial trials; fresh per-search TT, Hash16, one worker. Evaluators have different trees; NPS is not a pure implementation speedup. CPU from Windows process accounting, release wall and engine time separate. Mate/early/short cases retained but excluded from aggregate ratios."}
    assert data["signature"] == signature
    done = {(r["repeat"], r["position"], r["mode"], r["budget"], r["build"]) for r in data["records"]}
    with ExitStack() as stack:
        engines = {k: stack.enter_context(open_engine(v)) for k, v in BUILDS.items()}
        for label, engine in engines.items():
            config = BASE_OPTIONS | {"Evaluator": "classical" if label == "classical" else "nnue" if label == "v2" else "nnue_v3"}
            if label == "v3":
                config = {"NNUEV3File": str(MODEL.resolve())} | config
            engine.configure(config)
        for repeat in range(args.repeats):
            for index, position in enumerate(positions()):
                for mode, budget in [("nodes", b) for b in signature["nodes"]] + [("time", b) for b in signature["time_ms"]]:
                    labels = list(engines)
                    offset = (index + repeat) % 3
                    for label in labels[offset:] + labels[:offset]:
                        key = (repeat, position["id"], mode, budget, label)
                        if key in done:
                            continue
                        before = process_cpu(engines[label].transport.get_pid())
                        row = capture(engines[label], position, mode, budget)
                        after = process_cpu(engines[label].transport.get_pid())
                        data["records"].append(row | {"build": label, "repeat": repeat,
                            "cpu_seconds": after - before if before is not None and after is not None else None})
                    write_record(path, json.dumps(data, separators=(",", ":")) + "\n")
                print("Bench", repeat + 1, position["id"], flush=True)
    per_position, groups = [], defaultdict(dict)
    for row in data["records"]:
        groups[row["mode"], row["budget"], row["position"]].setdefault(row["build"], []).append(row)
    for (mode, budget, position), labels in groups.items():
        eligible = position not in ("mate_net", "defend_mate_net")
        for records in labels.values():
            eligible &= all(r["wall_seconds"] >= .01 and r["score_white"]["mate"] is None
                and (r["nodes"] == budget if mode == "nodes" else r["seconds"] >= budget / 1000 * .9) for r in records)
        medians = {label: {field: statistics.median(r[field] for r in records)
                           for field in ("nps", "wall_seconds", "nodes", "depth")} for label, records in labels.items()}
        per_position.append({"mode": mode, "budget": budget, "position": position, "eligible": bool(eligible),
            "v3_v2_nps": medians["v3"]["nps"] / medians["v2"]["nps"],
            "v3_classical_nps": medians["v3"]["nps"] / medians["classical"]["nps"],
            "v2_classical_nps": medians["v2"]["nps"] / medians["classical"]["nps"], "medians": medians})
    summary = []
    for mode, budget in sorted({(r["mode"], r["budget"]) for r in per_position}):
        selected = [r for r in per_position if (r["mode"], r["budget"]) == (mode, budget) and r["eligible"]]
        row = {"mode": mode, "budget": budget, "eligible": len(selected),
               **{key: geometric([r[key] for r in selected]) for key in ("v3_v2_nps", "v3_classical_nps", "v2_classical_nps")},
               "v3_v2_selected_fen_bootstrap95": interval([r["v3_v2_nps"] for r in selected]),
               "v3_v2_position_min_median_max": [min(r["v3_v2_nps"] for r in selected), statistics.median(r["v3_v2_nps"] for r in selected), max(r["v3_v2_nps"] for r in selected)]}
        for label in BUILDS:
            records = [r for r in data["records"] if r["mode"] == mode and r["budget"] == budget
                       and r["build"] == label and r["position"] in {p["position"] for p in selected}]
            row[label] = {"mean_nodes": statistics.mean(r["nodes"] for r in records),
                "mean_depth": statistics.mean(r["depth"] for r in records),
                "mean_wall_ms": statistics.mean(r["wall_seconds"] for r in records)*1000,
                "single_core_cpu_percent": sum(r["cpu_seconds"] for r in records)/sum(r["wall_seconds"] for r in records)*100
                    if all(r["cpu_seconds"] is not None for r in records) else None,
                "mean_root_move_changes": statistics.mean(sum(a["pv"][:1] != b["pv"][:1] for a,b in zip(r["iterations"], r["iterations"][1:])) for r in records)}
        summary.append(row)
    write_record(ROOT / "benchmark-summary.json", json.dumps({"summary": summary, "per_position": per_position}, indent=2) + "\n")
    with (ROOT / "benchmark-summary.csv").open("w", newline="", encoding="utf-8") as stream:
        fields = ["mode", "budget", "position", "eligible", "v3_v2_nps", "v3_classical_nps", "v2_classical_nps"]
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(per_position)
    print("Completed", len(data["records"]), "searches")


if __name__ == "__main__":
    main()
