"""Summarize paired release measurements without pooling unlike chess trees."""
from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
import random
import statistics

from tools.nnue_throughput import ROOT, save


def geometric(values: list[float]) -> float:
    return math.exp(statistics.mean(math.log(x) for x in values))


def interval(values: list[float], geometric_mean: bool = False) -> list[float]:
    rng = random.Random(20261019)
    sample = geometric if geometric_mean else statistics.mean
    draws = sorted(sample(rng.choices(values, k=len(values))) for _ in range(10000))
    return [draws[249], draws[9749]]


def summarize(path: Path) -> dict:
    data = json.loads(path.read_text())
    rows, summary, per_position = data["records"], [], []
    labels = sorted({r["build"] for r in rows} - {"baseline", "classical"})
    assert len(labels) == 1
    label = labels[0]
    for mode, budget in sorted({(r["mode"], r["budget"]) for r in rows}):
        eligible, gains, ratios_before, ratios_after, depth_changes, trials = [], [], [], [], [], []
        for position in sorted({r["position"] for r in rows}):
            grouped = {name: [r for r in rows if (r["mode"], r["budget"], r["position"], r["build"]) ==
                             (mode, budget, position, name)] for name in ("baseline", label, "classical")}
            assert len({len(v) for v in grouped.values()}) == 1 and all(grouped.values())
            wall = {k: statistics.median(r["wall_seconds"] for r in v) for k, v in grouped.items()}
            # Engine milliseconds are discretized; wall includes protocol/TT startup.
            nps = {k: statistics.median(r["nodes"] / r["seconds"] for r in v if r["seconds"] > 0)
                   if any(r["seconds"] > 0 for r in v) else 0 for k, v in grouped.items()}
            depth = {k: statistics.mean(r["depth"] for r in v) for k, v in grouped.items()}
            use = position not in ("mate_net", "defend_mate_net") and all(
                r["seconds"] >= .01 and (mode != "nodes" or r["nodes"] == budget)
                for v in grouped.values() for r in v)
            gain = wall["baseline"] / wall[label]
            trial_ratios = [a["wall_seconds"] / b["wall_seconds"] for a, b in zip(
                sorted(grouped["baseline"], key=lambda r: r["repeat"]), sorted(grouped[label], key=lambda r: r["repeat"]))]
            entry = {"position": position, "mode": mode, "budget": budget, "eligible": use,
                     "median_wall_seconds": wall, "median_engine_nps": nps, "mean_depth": depth,
                     "wall_speedup": gain, "trial_speedup_min_max": [min(trial_ratios), max(trial_ratios)],
                     "nnue_classical_before": nps["baseline"] / nps["classical"] if nps["classical"] else None,
                     "nnue_classical_after": nps[label] / nps["classical"] if nps["classical"] else None,
                     "cpu_single_core_percent": {k: statistics.mean(r["cpu_seconds"] / r["wall_seconds"] * 100 for r in v)
                                                  if all(r.get("cpu_seconds") is not None for r in v) else None
                                                  for k, v in grouped.items()}}
            per_position.append(entry)
            if use:
                eligible.append(position)
                gains.append(gain)
                ratios_before.append(entry["nnue_classical_before"])
                ratios_after.append(entry["nnue_classical_after"])
                depth_changes.append(depth[label] - depth["baseline"])
                trials.extend(trial_ratios)
        before, after = geometric(ratios_before), geometric(ratios_after)
        summary.append({"mode": mode, "budget": budget, "eligible": len(eligible),
                        "geomean_wall_speedup": geometric(gains), "wall_speedup_position_bootstrap95": interval(gains, True),
                        "geomean_nps_baseline_classical": before, "geomean_nps_optimized_classical": after,
                        "geomean_nps_speedup": after / before,
                        "gap_closed_fraction": (after - before) / (1 - before),
                        "mean_depth_change": statistics.mean(depth_changes),
                        "position_speedup_min_median_max": [min(gains), statistics.median(gains), max(gains)],
                        "regression_positions_wall": [r["position"] for r in per_position if r["mode"] == mode and
                            r["budget"] == budget and r["eligible"] and r["wall_speedup"] < 1],
                        "trial_speedup_min_median_max": [min(trials), statistics.median(trials), max(trials)]})
    result = {"input": str(path), "candidate": label,
              "method": "Per-position medians then geometric means. 10k seeded position bootstrap; descriptive selected-suite uncertainty, not population confidence. Mate fixtures, early fixed-node stops, and any sub-10ms trial excluded from aggregate throughput only. Timed wall speedup is descriptive duration ratio; use NPS/nodes/depth for timed gains. Gap closure=(after NNUE/classical ratio-before)/(1-before).",
              "summary": summary, "per_position": per_position}
    output = path.with_name(path.stem + "-summary.json")
    save(output, result)
    csv_path = output.with_suffix(".csv")
    with csv_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(["position", "mode", "budget", "eligible", "baseline_wall_s", "optimized_wall_s", "wall_speedup", "baseline_nnue_classical_nps", "optimized_nnue_classical_nps", "depth_change"])
        for r in per_position:
            writer.writerow([r["position"], r["mode"], r["budget"], r["eligible"], r["median_wall_seconds"]["baseline"],
                             r["median_wall_seconds"][label], r["wall_speedup"], r["nnue_classical_before"],
                             r["nnue_classical_after"], r["mean_depth"][label] - r["mean_depth"]["baseline"]])
    print(json.dumps(summary, indent=2))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    summarize(parser.parse_args().path)
