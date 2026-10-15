"""Separate logical accumulator work, clock instrumentation and release speed."""
from __future__ import annotations

from contextlib import ExitStack
import json
import statistics
import subprocess

from tools.nnue_diagnosis import (BASE_OPTIONS, DIAGNOSTIC, PROFILE, RELEASE, ROOT,
                                 capture, metadata, open_engine, prepare_suite, save)


def canonical(record: dict) -> dict:
    return {key: record[key] for key in ("move", "score_white", "depth", "nodes", "seldepth", "pv", "counters")}


def verify_counts(record: dict) -> None:
    d = record["diagnostics"]
    assert d["visits"] == record["nodes"]
    assert d["qvisits"] == record["counters"]["qnodes"]
    assert d["evaluation_calls"] == record["counters"]["nnue_evaluations"]
    assert d["updates"] == d["copies"] == sum(d["delta_histogram"])
    assert d["updates"] == d["normal_updates"] + d["q_updates"] + d["unvisited_updates"]
    assert d["evaluated_visits"] <= d["visits"]
    assert d["evaluated_qvisits"] <= d["qvisits"]
    assert d["unused_leaf_updates"] <= d["unused_updates"] <= d["updates"]
    assert d["unused_null_updates"] <= d["null_updates"] == record["counters"]["null_attempts"]
    assert d["refreshes"] == 1
    assert d["frame_bytes"] == 664 and d["stack_bytes"] == 65 * 664
    assert d["copy_payload_bytes"] == d["updates"] * (2 * 32 * 4 + 152)


def main() -> None:
    suite = prepare_suite()
    path = ROOT / "accumulator-profile.json"
    if path.exists():
        raise ValueError("Frozen profile already exists")
    builds = {"release": RELEASE, "counters": DIAGNOSTIC, "clock_profile": PROFILE}
    data = {"method": "Three serial rotated repeats per build and position, 100k nodes and 200ms. Release NPS is authoritative. Counter and clock builds are measured separately; clocks perturb tiny scopes. Logical copy payload is 408 bytes/update (256 float lanes + 152 feature metadata), read+write double that; not measured DRAM traffic. Delta rows count one perspective; both perspectives are included in byte estimates. Unused updates mean a frame never evaluated directly; unused leaves additionally had no evaluated descendant. Pending rows are uncancelled sums since the nearest evaluated ancestor (root already materialized), not an implemented lazy algorithm or measured speedup.",
            "builds": {name: metadata(binary) for name, binary in builds.items()}, "records": [], "micro": []}
    with ExitStack() as stack:
        engines = {name: stack.enter_context(open_engine(binary)) for name, binary in builds.items()}
        for engine in engines.values():
            engine.configure(BASE_OPTIONS | {"Evaluator": "nnue"})
        for repeat in range(3):
            labels = list(engines)
            labels = labels[repeat:] + labels[:repeat]
            for row in suite["positions"]:
                fixed = {}
                for label in labels:
                    for mode, budget in (("nodes", 100000), ("time", 200)):
                        record = capture(engines[label], row, mode, budget)
                        record.update(build=label, repeat=repeat)
                        if label != "release":
                            verify_counts(record)
                        if mode == "nodes":
                            fixed[label] = canonical(record)
                        data["records"].append(record)
                assert fixed["release"] == fixed["counters"] == fixed["clock_profile"], row["id"]
                print("Accumulator profile", repeat + 1, row["id"], flush=True)
    micro = RELEASE.with_name("micro.exe")
    data["micro_metadata"] = metadata(micro)
    data["cpu"] = json.loads(subprocess.check_output([str(micro.resolve()), "--cpu"], text=True, timeout=10))
    # The preserved developer microbenchmark excludes child make/unmake. Its
    # isolated copy loop copies lanes only, not feature metadata or full frames.
    for repeat in range(5):
        for row in suite["positions"][::2]:
            record = json.loads(subprocess.check_output([str(micro.resolve()), row["fen"], "100000", "scalar"], text=True, timeout=60))
            data["micro"].append({"position": row["id"], "repeat": repeat, **record})
    aggregate = {}
    for label in builds:
        rows = [r for r in data["records"] if r["build"] == label and r["mode"] == "nodes"]
        summary = {"searches": len(rows), "nodes": sum(r["nodes"] for r in rows),
                   "wall_seconds": sum(r["wall_seconds"] for r in rows)}
        if label != "release":
            keys = [key for key, value in rows[0]["diagnostics"].items() if isinstance(value, int) and not key.startswith("maximum") and key not in ("frame_bytes", "stack_bytes")]
            counts = {key: sum(r["diagnostics"][key] for r in rows) for key in keys}
            summary["counts"] = counts
            summary["updates_per_node"] = counts["updates"] / counts["visits"]
            summary["evaluation_node_fraction"] = counts["evaluated_visits"] / counts["visits"]
            summary["unused_update_fraction"] = counts["unused_updates"] / counts["updates"]
            summary["unused_leaf_update_fraction"] = counts["unused_leaf_updates"] / counts["updates"]
            summary["mean_pending_edges_per_first_evaluation"] = counts["pending_edges"] / counts["evaluated_frames"]
            summary["mean_pending_rows_per_first_evaluation"] = counts["pending_rows"] / counts["evaluated_frames"]
        aggregate[label] = summary
    data["aggregate_fixed_nodes"] = aggregate
    data["micro_summary_ns"] = {key: {"median": statistics.median(r[key] for r in data["micro"]),
                                      "min": min(r[key] for r in data["micro"]), "max": max(r[key] for r in data["micro"])}
                                for key in ("copy_ns", "move_update_ns", "refresh_ns", "head_ns", "classical_ns")}
    save(path, data)


if __name__ == "__main__":
    main()
