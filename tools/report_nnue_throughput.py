"""Build the throughput report and evidence manifest from completed measurements."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
import os
from pathlib import Path
import random
import statistics
import subprocess

from tools.nnue_throughput import ART, ROOT, MODEL, MODEL_SHA, save
from tools.nnue_diagnosis import positions, sha
from tools.analyze_nnue_throughput import geometric
from tools.analyze_nnue_diagnosis import cohort, pair_scores, interval, move_metrics


def read(name: str) -> dict:
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def pct(value: float) -> str:
    return f"{100 * value:.1f}%"


def validation() -> dict:
    raw = read("validation-500ms.json")
    assert raw["requested_games"] == len(raw["games"]) == 35 and raw["movetime_ms"] == 500
    assert raw["incomplete_last_pair"]
    paired_games = raw["games"][:34]
    result = cohort(paired_games)
    result["paired_completed_game_score"] = result["score"]
    result["paired_games"] = 34
    result["paired_wdl_unfinished"] = [result[k] for k in ("wins", "draws", "losses", "unfinished")]
    counts = Counter(g["candidate_outcome"] for g in raw["games"])
    result.update(games=35, wins=counts["win"], draws=counts["draw"], losses=counts["loss"], unfinished=counts["unfinished"])
    completed = counts["win"] + counts["draw"] + counts["loss"]
    points = counts["win"] + counts["draw"] / 2
    result["score"] = points / completed
    result["unfinished_worst_best_score"] = [points / 35, (points + counts["unfinished"]) / 35]
    last = raw["games"][-1]
    result["unpaired_game"] = {key: last[key] for key in ("game", "pair", "candidate_color", "result", "candidate_outcome", "termination", "plies")}
    result["nnue"] = move_metrics(raw["games"], True)
    result["classical"] = move_metrics(raw["games"], False)
    result["game_wall_seconds"] = sum(g["wall_seconds"] for g in raw["games"])
    result["termination_counts"] = dict(Counter(g["termination"] for g in raw["games"]))
    result["optimized"] = result.pop("nnue")
    result["baseline"] = result.pop("classical")
    groups = defaultdict(list)
    for pair, value in pair_scores(paired_games).items():
        groups[raw["openings"][pair - 1]["family"]].append(value)
    families = list(groups.values())
    rng = random.Random(20261019)
    samples = []
    for _ in range(20000):
        selected = rng.choices(families, k=len(families))
        samples.append(sum(map(sum, selected)) / sum(map(len, selected)))
    result["family_cluster_complete_pair_bootstrap95"] = interval(samples)
    result["method"] = "User-amended stop at 35 completed games, 500ms. First 34 games form 17 complete opening pairs and supply all paired uncertainty/Elo. Game 35 is unpaired and reported separately; full WDL/score includes it. 20k pair bootstrap/censoring sensitivity, supplementary family clusters. Human mid-run stop, not automatically expanded or outcome-based by the engine. Caps unknown, never draws."
    save(ROOT / "validation-summary.json", result)
    return result


def plots(nodes: dict, timed: dict) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 3, figsize=(16, 5), constrained_layout=True)
    rows = nodes["summary"]
    x = list(range(len(rows)))
    values = [r["geomean_wall_speedup"] for r in rows]
    axes[0].errorbar(x, values, yerr=[[v - r["wall_speedup_position_bootstrap95"][0] for v, r in zip(values, rows)],
                                    [r["wall_speedup_position_bootstrap95"][1] - v for v, r in zip(values, rows)]], fmt="o", capsize=5, color="#176b86")
    axes[0].axhline(1, color="gray", linestyle="--")
    axes[0].set_xticks(x, [f"{r['budget'] // 1000}k" for r in rows])
    axes[0].set_ylim(.9, max(1.4, max(r["wall_speedup_position_bootstrap95"][1] for r in rows) + .05))
    axes[0].set(title="Identical-work wall speedup", xlabel="Node budget", ylabel="Baseline / optimized elapsed time")
    rows = timed["summary"]
    x = list(range(len(rows)))
    axes[1].plot(x, [r["geomean_nps_baseline_classical"] for r in rows], "o-", label="Baseline NNUE")
    axes[1].plot(x, [r["geomean_nps_optimized_classical"] for r in rows], "o-", label="Optimized NNUE")
    axes[1].axhline(1, color="gray", linestyle="--", label="Frozen classical")
    axes[1].set_xticks(x, [str(r["budget"]) for r in rows])
    axes[1].set_ylim(0, 1.1)
    axes[1].set(title="Timed whole-search throughput", xlabel="Milliseconds / move", ylabel="NNUE / classical NPS")
    axes[1].legend(fontsize=9)
    rows = [r for r in nodes["per_position"] if r["budget"] == 1000000 and r["eligible"]]
    rows.sort(key=lambda r: r["wall_speedup"])
    axes[2].barh(range(len(rows)), [100 * (r["wall_speedup"] - 1) for r in rows], color=["#a64242" if r["wall_speedup"] < 1 else "#176b86" for r in rows])
    axes[2].set_yticks(range(len(rows)), [r["position"] for r in rows], fontsize=7)
    axes[2].axvline(0, color="gray")
    axes[2].set(title="Per-position 1M-node results", xlabel="Wall throughput improvement (%)")
    fig.suptitle("Compact v2: exact search semantics, repeated release measurements", fontsize=14)
    fig.savefig(ROOT / "throughput.png", dpi=180)
    fig.savefig(ROOT / "throughput.svg")
    plt.close(fig)
    path = ROOT / "throughput.svg"
    path.write_text("\n".join(line.rstrip() for line in path.read_text().splitlines()) + "\n", encoding="utf-8", newline="\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plots", action="store_true")
    args = parser.parse_args()
    # Canonicalize only this new study's text copies before byte hashing. Native
    # logs and every prior research artifact remain untouched.
    for path in ROOT.iterdir():
        if path.is_file() and path.suffix in (".json", ".csv", ".pgn", ".md", ".txt", ".svg") and not path.name.endswith(("-checkpoint.json", ".progress.json")):
            raw = path.read_bytes()
            canonical = raw.replace(b"\r\n", b"\n")
            if canonical != raw:
                path.write_bytes(canonical)
    baseline, nodes, timed = read("baseline.json"), read("benchmark-final-summary.json"), read("benchmark-final-time-summary.json")
    final, sanitizer = read("correctness-final.json"), read("correctness-ubsan.json")
    initial, detailed = read("initial-analysis.json"), read("detailed-profile.json")
    all_work = read("work-counters.json")
    assert len(all_work["records"]) == 72
    work = {}
    for label in ("legacy_clocks", "optimized_counters"):
        rows = [r for r in detailed["records"] if r["build"] == label]
        counters = Counter()
        for row in rows:
            counters.update({key: value for key, value in row["diagnostics"].items() if isinstance(value, int)})
        work[label] = {"searches": len(rows), "nodes": sum(r["nodes"] for r in rows),
                       "allocation_count": sum(r["profile"]["allocations"] for r in rows) if all("profile" in r for r in rows) else None,
                       **{key: counters[key] for key in ("evaluation_calls", "updates", "refreshes", "delta_rows", "copy_payload_bytes", "row_weight_bytes", "qvisits", "q_updates")}}
    assert work["legacy_clocks"]["updates"] == work["optimized_counters"]["updates"]
    assert work["legacy_clocks"]["delta_rows"] == work["optimized_counters"]["delta_rows"]
    save(ROOT / "work-summary.json", {"method": "Same 24 FENs at 400k nodes. Logical source payload, not DRAM traffic. Clock-build allocations include instrumented search scope only; counter-only builds do not measure allocations.", "builds": work})
    cpu = []
    for filename in ("benchmark-final.json", "benchmark-final-time.json"):
        raw = read(filename)["records"]
        for mode, budget, build_name in sorted({(r["mode"], r["budget"], r["build"]) for r in raw}):
            rows = [r for r in raw if (r["mode"], r["budget"], r["build"]) == (mode, budget, build_name)]
            assert all(r.get("cpu_seconds") is not None for r in rows)
            cpu.append({"mode": mode, "budget": budget, "build": build_name,
                        "single_core_percent": sum(r["cpu_seconds"] for r in rows) / sum(r["wall_seconds"] for r in rows) * 100})
    save(ROOT / "cpu-summary.json", {"method": "Windows process user+kernel CPU / UCI wall, pooled over all FEN/trials. OS accounting is coarse for short runs. 100% means one fully utilized logical CPU, not the whole 12-CPU machine.", "records": cpu})
    timed_details = []
    timed_raw = read("benchmark-final-time.json")["records"]
    for budget in (50, 200, 1000):
        item = {"milliseconds": budget, "builds": {}}
        for name in ("baseline", "final", "classical"):
            rows = [r for r in timed_raw if r["budget"] == budget and r["build"] == name and r["position"] not in ("mate_net", "defend_mate_net")]
            changes, swings = [], []
            for r in rows:
                moves = [i["pv"][0] for i in r["iterations"] if i["pv"]]
                changes.append(sum(a != b for a, b in zip(moves, moves[1:])))
                scores = [i["score_white"]["cp"] for i in r["iterations"] if i["score_white"]["cp"] is not None]
                swings.append(max((abs(a-b) for a, b in zip(scores, scores[1:])), default=0))
            item["builds"][name] = {"mean_nodes": statistics.mean(r["nodes"] for r in rows),
                 "mean_wall_ms": statistics.mean(r["wall_seconds"] for r in rows) * 1000,
                 "mean_engine_ms": statistics.mean(r["seconds"] for r in rows) * 1000,
                 "mean_completed_depth": statistics.mean(r["depth"] for r in rows),
                 "mean_iteration_root_move_changes": statistics.mean(changes),
                 "median_max_iteration_cp_swing": statistics.median(swings)}
        timed_details.append(item)
    save(ROOT / "timed-search-details.json", {"method": "All five trials on 22 non-mate FENs. Stability is descriptive, not quality or independent trials. Swings compare consecutive finite completed-iteration scores; mate reports are separate in raw records.", "records": timed_details})
    match = validation()
    assert sha(MODEL) == MODEL_SHA
    assert sha(ART / "final/engine.exe") == final["candidate"]["sha256"]
    assert sha(ART / "baseline/engine.exe") == final["baseline"]["sha256"]
    for filename, expected in (("benchmark-final.json", 1080), ("benchmark-final-time.json", 1080)):
        assert len(read(filename)["records"]) == expected
    assert len(final["searches"]) == len(sanitizer["searches"]) == 240
    unchanged = []
    for source in (ART / "baseline-source").glob("*"):
        live = Path("engine/src") / source.name
        if sha(source) == sha(live):
            unchanged.append(source.name)
    for required in ("evaluation.cpp", "evaluation.hpp", "search_policy.hpp", "transposition.hpp", "main.cpp"):
        assert required in unchanged, required
    verification = {"model_sha256": sha(MODEL), "unchanged_engine_sources": unchanged,
                    "baseline_executable_sha256": final["baseline"]["sha256"],
                    "optimized_executable_sha256": final["candidate"]["sha256"],
                    "baseline_code_section_sha256": baseline["text_sha256"],
                    "final_tests": (ROOT / "final-tests.txt").read_text().splitlines()[-1],
                    "final_exact_cases": len(final["searches"]), "ubsan_exact_cases": len(sanitizer["searches"]),
                    "asan": read("asan-availability.json"), "native_transition_oracle": final["move_transition_oracle"],
                    "corpus": final["heldout_random_extreme"], "golden": final["golden"],
                    "gui": json.loads((ART / "gui/gui-verification.json").read_text()),
                    "match_replay": read("validation-replay.json")}
    if (ROOT / "desktop-verification.json").exists():
        verification["desktop"] = read("desktop-verification.json")
        assert verification["desktop"]["visually_inspected"]
    verification["application_runtime"] = read("application-runtime.json")
    save(ROOT / "verification-summary.json", verification)
    if args.plots:
        plots(nodes, timed)
    main_result = next(r for r in nodes["summary"] if r["budget"] == 1000000)
    report = ["# StockBear Compact v2 — Whole-Search Throughput Optimization", "",
              "## Executive summary", "",
              f"The accepted change removes redundant sorted piece-feature metadata maintenance from NNUE child-state updates. At 1M nodes, whole-search wall throughput improved **{100 * (main_result['geomean_wall_speedup'] - 1):.1f}%**; the selected-position bootstrap range is **{100 * (main_result['wall_speedup_position_bootstrap95'][0] - 1):.1f}–{100 * (main_result['wall_speedup_position_bootstrap95'][1] - 1):.1f}%**. NNUE/classical NPS moved from **{pct(main_result['geomean_nps_baseline_classical'])} to {pct(main_result['geomean_nps_optimized_classical'])}**, closing **{pct(main_result['gap_closed_fraction'])}** of the contemporaneously measured throughput gap.", "",
              "The model, float32 arithmetic order, score contract, search algorithms, pruning, ordering, TT policy, time management and classical evaluation are preserved. Classical remains the UCI/application default. Eager updates remain enabled. No training or NNUE v3 work was performed.", "",
              f"The final release and UBSan builds each matched **240 deterministic search cases** across both evaluators. The full suite reports **{verification['final_tests']}**. All native transition/corpus/golden gates passed. The user amended the initial 60-game schedule to **35 completed games at 500ms/move**: 17 complete opening pairs plus one separately reported unpaired game. The first smoke pair remains included.", "",
              "## Baseline and measurement methodology", "",
              f"Frozen revision `{baseline['revision']}`; tag `nnue-v2-throughput-baseline-a2fb045`. The untouched rebuilt baseline matched the preserved release's code-section SHA256 `{baseline['text_sha256']}`. Compiler: Zig {baseline['compiler_version']}, C++17, `-O2 -ffp-contract=off`, portable scalar float32; no fast-math, LTO, model precision change or explicit SIMD. CPU: 13th Gen Intel Core i5-13420H, 12 logical processors, Windows/Python 3.11.8. No affinity or frequency lock; no concurrent CPU-heavy experiments.", "",
              "The same 24 legal FENs from the prior diagnosis cover 12 categories. Final release tests use five trials at 100k/400k/1M nodes and 50/200/1000ms: 2,160 searches, plus a direct five-trial classical A/B check. Run order rotates by position and trial. Each capture uses a fresh game/search TT, Hash=16MB and one search worker; each binary uses the same scalar/incremental/model/search options. Classical is measured in the preserved baseline executable.", "",
              "Per-position trial medians are aggregated geometrically. Two short mate fixtures, early fixed-node terminations and any sub-10ms trial are excluded from aggregate throughput only; raw records retain everything. Intervals resample selected FENs 10,000 times and are descriptive suite sensitivity, not confidence about arbitrary chess positions. Repeated trials and per-position ranges remain in JSON/CSV. UCI wall time includes communication and fresh TT setup; engine time is separately recorded in milliseconds. Timed trees may differ because faster search reaches more work, so fixed-node results are the primary implementation-speed evidence.", "",
              "## Profiling findings", "",
              f"Before optimization, 432 serial searches across release/counters/clocks produced identical trees. Total wall: release {initial['wall_seconds']['release']:.3f}s, counters {initial['wall_seconds']['counters']:.3f}s, clocks {initial['wall_seconds']['clocks']:.3f}s. Counter overhead was {100 * (initial['counter_overhead_ratio'] - 1):.1f}%; clock overhead was {100 * (initial['clock_overhead_ratio'] - 1):.1f}%. Clock percentages are **not production runtime shares**.", "",
              "Windows WPR CPU sampling failed to enable the OS profiling policy (`0xc5585011`). Hardware cache/branch/memory-bandwidth counters were unavailable. Existing scoped clocks, exact logical counters and release differential measurements were used instead. Detailed clocks separately cover move generation, make/unmake, delta construction, state extraction, metadata, rows, copy, root refresh, head, table operations, search bookkeeping and allocations. Quiescence work is identified by node/update counters; overlapping qsearch time is not added to exclusive categories.", "",
              "| Rank | Candidate cost | Evidence / decision |", "| --- | --- | --- |",
              "| 1 | Redundant full sorted piece-feature metadata per edge | Removing it yields the accepted repeatable release improvement; this is the largest demonstrated recoverable cost. |",
              "| 2 | Row-update/delta/state bookkeeping | Still performed in exact feature order; head and row loops remain otherwise unchanged. Differential fusion did not improve eager compact. |",
              "| 3 | NNUE head | Significant instrumented scope, already transposed and fast; no evidence justifying a new SIMD/quantized implementation. |",
              "| 4 | Fully unused frames | Cached deferral bounds replay but adds readiness/storage overhead; direct timing rejected it. |",
              "| 5 | Lane copying | Prior 1.74ns isolated copy and timer distortion do not establish it as the primary bottleneck. No standalone memcpy optimization accepted. |",
              "| 6 | Root refresh / allocations | Per-search setup; root refresh is tiny in the trace. Fresh TT construction is outside profile scopes, but included in wall time. No per-node NNUE allocation introduced. |", "",
              "Detailed measured scope times and work counts are in [detailed-profile.json](docs/nnue-v2-throughput/detailed-profile.json). They cannot identify physical cache misses or assign a precise release-time percentage to metadata alone. The accepted implementation is a small bundle of metadata/state lookup changes, not a causal Elo allocation.", "",
              f"The identical 24-FEN 400k-node detailed workload used {work['legacy_clocks']['nodes']:,} visits, {work['legacy_clocks']['evaluation_calls']:,} evaluations, {work['legacy_clocks']['updates']:,} updates, {work['legacy_clocks']['delta_rows']:,} changed rows per perspective and {work['legacy_clocks']['refreshes']} root refreshes. These counts are unchanged. Logical copied payload fell from {work['legacy_clocks']['copy_payload_bytes']/1e9:.3f}GB to {work['optimized_counters']['copy_payload_bytes']/1e9:.3f}GB. Root stack storage remains 664 bytes/frame and 43,160 bytes total; this optimization does not shrink that stack. The payload estimate includes metadata generated/stored, not a measured physical memcpy or cache-traffic count. [Work summary](docs/nnue-v2-throughput/work-summary.json).", "",
              "## Optimization experiments", "",
              "All candidate screening builds passed 96 exact search cases, all kernel-switch checks and the bitwise move/null oracle before timing. Screening: three 400k-node trials. Later alternatives also received direct five-trial duels against eager compact.", "",
              "| Candidate | Hypothesis and change | Screening wall speed vs baseline | Decision |", "| --- | --- | --- | --- |"]
    decisions = {"merge": "Rejected: gain not established", "compact": "Accepted: final verification passed",
                 "deferred": "Rejected: slower than eager compact", "fused": "Rejected: no additional reliable gain",
                 "compact-small": "Rejected: smaller temporary, no reliable runtime gain"}
    hypotheses = {"merge": "Single merge instead of repeated list shifts", "compact": "Retain sorted state rows only; preserve full float sums",
                  "deferred": "Cache every materialized intermediate ancestor", "fused": "Keep each lane live through ordered row operations",
                  "compact-small": "24-byte state extraction temporary instead of 152 bytes"}
    for label in decisions:
        r = read(f"benchmark-{label}-summary.json")["summary"][0]
        report.append(f"| {label} | {hypotheses[label]} | {r['geomean_wall_speedup']:.3f}× [{r['wall_speedup_position_bootstrap95'][0]:.3f}, {r['wall_speedup_position_bootstrap95'][1]:.3f}] | {decisions[label]} |")
    report += ["", "Direct speed relative to eager compact (above one favors the alternative):", ""]
    for label in ("deferred", "fused", "compact-small"):
        r = read(f"duel-compact-{label}-nnue.json")["summary"]
        report.append(f"- {label}: {r['geomean_first_over_second']:.3f}×, interval [{r['position_bootstrap95'][0]:.3f}, {r['position_bootstrap95'][1]:.3f}].")
    report += ["", "The search-only invariant is that legal move generation supplies the move, its delta is captured before make, after-move state features retain legal-EP and clean-castling checks, and children use distinct stack storage. Full roots refresh. Subsequent move-derived updates read prior state features; they do not need sorted piece lists. The redundant missing-piece lookup in those lists is removed only in this trusted API. The general full-feature updater retains validation and remains the independent arithmetic reference. Reference/quantized kernels keep the legacy full-metadata path. Kernel selection is immutable within a search; switches refresh roots. No float row arithmetic is reassociated.", "",
               "Deferral's exact invariant, head-call materialization point, 64-ply worst chain, at-most-once intermediate caching and approximately 11.7KB extra pending storage are documented in [EXPERIMENTS.md](docs/nnue-v2-throughput/EXPERIMENTS.md). It never replays from evaluated ancestors alone. Its row work is bounded by eager work for an identical tree, yet release runtime regressed. Eager updates therefore remain the production path. Rejected prototypes are compile-time options and omitted from ordinary builds.", "",
               "## Final fixed-node benchmarks", "",
               "| Nodes | Eligible FENs | Wall speedup | Selected-FEN 95% interval | NNUE/classical NPS before→after | Gap closed |", "| --- | --- | --- | --- | --- | --- |"]
    for r in nodes["summary"]:
        report.append(f"| {r['budget']:,} | {r['eligible']} | {r['geomean_wall_speedup']:.3f}× | [{r['wall_speedup_position_bootstrap95'][0]:.3f}, {r['wall_speedup_position_bootstrap95'][1]:.3f}] | {pct(r['geomean_nps_baseline_classical'])}→{pct(r['geomean_nps_optimized_classical'])} | {pct(r['gap_closed_fraction'])} |")
    report += ["", "A separate counter-only pass measures work at every budget, matching the final release tree and pre-edit work counts exactly. Totals below include all 24 fixtures; these instrumented times are excluded from performance estimates.", "",
               "| Requested nodes | Evaluations | Accumulator updates | Root refreshes | Changed rows / perspective |", "| --- | --- | --- | --- | --- |"]
    for r in all_work["summary"]:
        report.append(f"| {r['budget']:,} | {r['evaluation_calls']:,} | {r['updates']:,} | {r['refreshes']} | {r['delta_rows']:,} |")
    report += ["", "Gap closure is `(optimized NNUE/classical − baseline NNUE/classical) / (1 − baseline NNUE/classical)`, using contemporaneous paired suite measurements. Historical 66–72% diagnosis values are context, not substituted into this formula. The target of 85–90% was aspirational, not an acceptance threshold.", "",
               "| FEN | 100k wall speed | 400k wall speed | 1M wall speed | 1M baseline→optimized median ms |", "| --- | --- | --- | --- | --- |"]
    for position in positions():
        rows = {r["budget"]: r for r in nodes["per_position"] if r["position"] == position["id"]}
        speeds = [f"{rows[b]['wall_speedup']:.3f}×" + ("*" if not rows[b]["eligible"] else "") for b in (100000, 400000, 1000000)]
        wall = rows[1000000]["median_wall_seconds"]
        report.append(f"| {position['id']} | {' | '.join(speeds)} | {wall['baseline']*1000:.2f}→{wall['final']*1000:.2f} |")
    report += ["", "Asterisks mark excluded short/early-terminating fixtures. All values remain observable; they are not pooled as reliable throughput estimates.", ""]
    for r in nodes["summary"]:
        regressions = ", ".join(r["regression_positions_wall"]) or "none"
        low, med, high = r["position_speedup_min_median_max"]
        report.append(f"- {r['budget']:,} nodes: position speedup min/median/max {low:.3f}/{med:.3f}/{high:.3f}×; median regressions: {regressions}. Individual reversals may reflect noise; no per-FEN significance claim is made.")
    low, med, high = main_result["trial_speedup_min_median_max"]
    report += ["", f"Across the individual eligible 1M-node FEN/trial comparisons, speedup min/median/max was {low:.3f}/{med:.3f}/{high:.3f}×. These repeated measurements expose system variation; they are not independent position samples."]
    report += ["", "## Final fixed-time benchmarks", "",
               "| ms | Eligible FENs | Baseline NNUE/classical NPS | Optimized NNUE/classical NPS | NNUE NPS gain | Mean completed-depth change |", "| --- | --- | --- | --- | --- | --- |"]
    for r in timed["summary"]:
        report.append(f"| {r['budget']} | {r['eligible']} | {pct(r['geomean_nps_baseline_classical'])} | {pct(r['geomean_nps_optimized_classical'])} | {100*(r['geomean_nps_speedup']-1):.1f}% | {r['mean_depth_change']:+.3f} |")
    report += ["", "Means below use all five trials on 22 non-mate FENs; each cell is baseline NNUE / optimized NNUE.", "",
               "| ms | Nodes searched | Actual wall ms | Engine ms | Completed depth | ID root-move changes |", "| --- | --- | --- | --- | --- | --- |"]
    for r in timed_details:
        a, b = r["builds"]["baseline"], r["builds"]["final"]
        report.append(f"| {r['milliseconds']} | {a['mean_nodes']:.0f} / {b['mean_nodes']:.0f} | {a['mean_wall_ms']:.2f} / {b['mean_wall_ms']:.2f} | {a['mean_engine_ms']:.2f} / {b['mean_engine_ms']:.2f} | {a['mean_completed_depth']:.2f} / {b['mean_completed_depth']:.2f} | {a['mean_iteration_root_move_changes']:.2f} / {b['mean_iteration_root_move_changes']:.2f} |")
    report += ["", "Fixed-time moves, scores, completed depths and PVs may differ because the implementation searches farther. This is expected and does not weaken the exact fixed-work gates. Complete per-iteration stability, nodes and timing are retained in raw JSON. More nominal depth or changed moves alone are not a playing-strength claim. Windows process CPU counters accompany final release trials; CPU/wall ratios include worker and small UCI activity and have OS accounting granularity. No extra search thread is added.", "",
               f"At 1M nodes, pooled process CPU/wall utilization was {next(r['single_core_percent'] for r in cpu if r['mode']=='nodes' and r['budget']==1000000 and r['build']=='baseline'):.1f}% baseline NNUE, {next(r['single_core_percent'] for r in cpu if r['mode']=='nodes' and r['budget']==1000000 and r['build']=='final'):.1f}% optimized NNUE and {next(r['single_core_percent'] for r in cpu if r['mode']=='nodes' and r['budget']==1000000 and r['build']=='classical'):.1f}% frozen classical, where 100% denotes one logical CPU. [CPU details](docs/nnue-v2-throughput/cpu-summary.json).", "",
               "## Correctness and classical preservation", "",
               f"- Baseline tests: {(ROOT/'baseline-tests.txt').read_text().splitlines()[-1]}. Final tests: {verification['final_tests']}.",
               "- Release and UBSan each: 24 FENs × two evaluators × depths 4/6 and 100k/400k/1M nodes = 240 exact cases; identical best moves, scores, PVs, nodes, selective depths and all search counters. The final repeated fixed-node benchmark additionally checks every paired NNUE result.",
               f"- Native bitwise oracle: {final['move_transition_oracle']['transitions']:,} real/sibling move transitions and {final['move_transition_oracle']['nulls']:,} null transitions, preserving every float lane and final score bit against the retained full-metadata implementation. Includes captures, promotions, castling, legal/illegal-EP state distinctions, long walks, sibling restoration and root refreshes.",
               f"- Held-out/random/extreme corpus: {final['heldout_random_extreme']['n']:,} outputs, maximum reference difference {final['heldout_random_extreme']['max_cp']:.6g}cp. Trained goldens: {final['golden']['n']}, maximum difference {final['golden']['max_cp']:.6g}cp. Generic scalar and integer transition oracles also pass; head extreme/clipping checks remain enabled.",
               "- UCI defaults identical; classical stays default. Kernel switching, evaluator switching, fresh TT/root refresh, 12 cancellations per checked build and five terminal/draw-history cases pass. GUI worker/time-preset/stale-result checks pass; the [minimum-size frame](docs/nnue-v2-throughput/gui-minimum.png) was inspected. A separate native Windows launch and [desktop frame](docs/nnue-v2-throughput/gui-desktop.png) are recorded in [desktop verification](docs/nnue-v2-throughput/desktop-verification.json).",
               "- Classical evaluator/constants, search-policy header, transposition implementation and UCI main source are byte-identical to the baseline source snapshot. Shared search edits are confined to NNUE state preparation/evaluation guards; all pruning, bounds, ordering, draw and time logic remain unchanged. Integrated `.text` changes because the NNUE call path changes, so final binary-wide code equality is not claimed; exact classical trees and the complete suite are the behavioral gates."]
    report += [f"- Normal application executable rebuilt with its original embedded v1 model and classical default, preserving the old executable separately. {len(verification['application_runtime']['searches'])} additional fixed-budget v1 runtime comparisons matched exactly. Compact v2 was used explicitly for every study measurement and the native desktop launch; no model-default migration is implied."]
    classical = read("duel-baseline-final-classical.json")["summary"]
    report += [f"- Direct classical release timing: {classical['geomean_first_over_second']:.3f}× baseline/final wall speed, selected-FEN interval [{classical['position_bootstrap95'][0]:.3f}, {classical['position_bootstrap95'][1]:.3f}]. This measures code-layout/system effects separately; it is not included in the frozen-classical denominator.", "",
               "UBSan ran the full parity, corpus and transition gates with no detected error. " + ("AddressSanitizer also passed its recorded gates." if verification["asan"]["available"] else "AddressSanitizer could not be built for the installed Windows compiler/target runtime; the exact failure is retained in `asan-availability.json`. No ASan pass is claimed, and no sanitizer runtime failure was ignored."), "",
               "| Identity | SHA256 |", "| --- | --- |",
               f"| Compact v2 model | `{MODEL_SHA}` |", f"| Untouched baseline executable | `{final['baseline']['sha256']}` |",
               f"| Final executable | `{final['candidate']['sha256']}` |", "",
               "Full compiler flags, source SHA256 maps, executable identities and platform metadata are recorded with every build/measurement. `--nnue-update compact` is now the build default; `--nnue-update legacy` selects the retained reference path. No default evaluator/model export/training configuration changed.", "",
               "## Bounded playing-strength validation", "",
               f"The original 60-game schedule was stopped at **35 completed games at 500ms/move**, following the user's mid-run instruction. The first 34 games comprise 17 evaluator-neutral opening pairs with reversed colors; game 35 is the White half of pair 18. Optimized NNUE vs frozen baseline NNUE, identical model/search settings. The smoke pair remains included. Full 35-game W–D–L–U: **{match['wins']}–{match['draws']}–{match['losses']}–{match['unfinished']}**; completed-game score **{pct(match['score'])}**; unknown-outcome bounds **{pct(match['unfinished_worst_best_score'][0])}–{pct(match['unfinished_worst_best_score'][1])}**.", "",
               f"**Paired analysis uses only games 1–34:** W–D–L–U {match['paired_wdl_unfinished']}, score {pct(match['paired_completed_game_score'])}. Pair-resampled 95% censoring sensitivity envelope: **{pct(match['paired_censoring_bootstrap_95_envelope'][0])}–{pct(match['paired_censoring_bootstrap_95_envelope'][1])}**. Complete-pair bootstrap: {match['complete_pairs']} pairs, interval {match['paired_bootstrap_95']}. Family-cluster complete-pair interval: {match['family_cluster_complete_pair_bootstrap95']}. Conditional paired-game Elo estimate: {match['relative_elo']:+.1f}; this small validation does **not** establish a universal Elo advantage.", "",
               f"**Unpaired game 35:** optimized played {match['unpaired_game']['candidate_color']}; result {match['unpaired_game']['result']} ({match['unpaired_game']['candidate_outcome']}), {match['unpaired_game']['plies']} total plies, {match['unpaired_game']['termination']}. It contributes to full descriptive WDL/NPS only and is excluded from paired uncertainty/Elo. It is not imputed as a complete opening pair.", "",
               f"Game NPS optimized/baseline: {match['optimized']['aggregate_nps']/1e6:.3f}M/{match['baseline']['aggregate_nps']/1e6:.3f}M; mean completed depth {match['optimized']['mean_completed_depth']:.2f}/{match['baseline']['mean_completed_depth']:.2f}. These are different played positions/trees, so fixed-FEN comparisons are the stronger implementation evidence. Terminations: {match['termination_counts']}. Total recorded game wall time {match['game_wall_seconds']/60:.1f} minutes.", "",
               "Claimable draw rules and the fixed 240 searched-ply cap were used without evaluation adjudication. Caps remain unfinished. The 35-game stop was a human runtime amendment, not an automatic decision from outcomes. The original 60-game plan/checkpoint is retained alongside the amendment; no additional completed games or extra classical tournament occurred. Independent JSON/PGN replay verifies every move, color, complete/partial opening pair, terminal result and executable hash. Only 17 complete pairs, selected openings and a mid-run human stop limit generalization and nominal uncertainty coverage. The study asks whether a semantics-preserving speed improvement produces practical search opportunities; it does not retest the neural model against classical at scale.", "",
               "## Answers and next steps", "",
               "1. **Largest recoverable overhead:** redundant full sorted piece-feature metadata maintenance on move-derived child updates. The release differential, not a microbenchmark or distorted timer share, establishes the useful target.",
               f"2. **Largest verified optimization:** eager compact state metadata, {100*(main_result['geomean_wall_speedup']-1):.1f}% whole-search wall throughput gain at 1M nodes. Other independent experiments did not justify production adoption.",
               f"3. **Gap closed:** {pct(main_result['gap_closed_fraction'])} at 1M nodes; the remaining measured NNUE/classical NPS gap is {pct(1-main_result['geomean_nps_optimized_classical'])}. Per-budget values appear above; no Elo gain is inferred from this formula.",
               "4. **Regressions:** all deterministic behaviors remain identical. Median timing regressions, trial variation and rejected slower experiments are explicitly listed. Deferral and fused loops stay experimental.",
               "5. **Further NNUE optimization:** possible, but use the remaining whole-search release profile. Current results do not justify a large lazy redesign or blindly restoring prior SIMD/quantization prototypes. Preserve this v2 engine as a reference and demand repeated gains for any new candidate.",
               "6. **Ready for king-relative v3?** Yes for a separately versioned research experiment with preserved v2 fallback, trained-feature contracts, grouped holdout, native parity and paired strength/throughput validation. This report does not prove king-relative features fix the earlier match gap. No v3 training or implementation starts here.", "",
               "## Evidence and reproduction", "",
               "[Study protocol and commands](docs/nnue-v2-throughput/README.md) · [Experiment contracts](docs/nnue-v2-throughput/EXPERIMENTS.md) · [Fixed-node JSON](docs/nnue-v2-throughput/benchmark-final.json) · [Fixed-node CSV](docs/nnue-v2-throughput/benchmark-final-summary.csv) · [Timed JSON](docs/nnue-v2-throughput/benchmark-final-time.json) · [Timed CSV](docs/nnue-v2-throughput/benchmark-final-time-summary.csv) · [Verification](docs/nnue-v2-throughput/verification-summary.json) · [Match summary](docs/nnue-v2-throughput/validation-summary.json) · [Match PGN](docs/nnue-v2-throughput/validation-500ms.pgn) · [Manifest](docs/nnue-v2-throughput/output-manifest.json).", "",
               "[Throughput figures](docs/nnue-v2-throughput/throughput.png) · [Vector figures](docs/nnue-v2-throughput/throughput.svg). Original research files and models remain separate. Build labels/binaries are immutable within the study; use fresh labels and paths for a new experiment. Generated native builds/logs/source snapshots are local under `artifacts/nnue-v2-throughput/`; committed raw evidence and report inputs are in the linked study directory.", ""]
    report_path = Path(os.environ.get("STOCKBEAR_THROUGHPUT_REPORT", "NNUE_V2_THROUGHPUT_OPTIMIZATION.md"))
    if ROOT != Path("docs/nnue-v2-throughput") and "STOCKBEAR_THROUGHPUT_REPORT" not in os.environ:
        raise ValueError("Fresh measurements require STOCKBEAR_THROUGHPUT_REPORT pointing to a new report file")
    report_text = "\n".join(report).replace("docs/nnue-v2-throughput/", ROOT.as_posix() + "/")
    report_path.write_text(report_text, encoding="utf-8", newline="\n")
    files = [p for p in ROOT.iterdir() if p.is_file() and p.name != "output-manifest.json" and not p.name.endswith((".tmp", "-checkpoint.json", ".progress.json"))]
    files.append(report_path)
    save(ROOT / "output-manifest.json", {"method": "SHA256 of canonical LF evidence files; checkpoint and scratch files excluded. Executables remain preserved locally and identified in baseline/final metadata.",
         "files": {str(p).replace('\\', '/'): sha(p) for p in sorted(files)},
         "tools_lf_sha256": {str(p).replace('\\', '/'): hashlib.sha256(p.read_bytes().replace(b'\r\n', b'\n')).hexdigest()
                              for p in sorted([*Path("tools").glob("*nnue_throughput*.py"), Path("tools/probe_nnue_asan.py"),
                                               Path("tests/test_nnue_throughput.py"), Path("tests/test_nnue_diagnosis.py")])}})
    print("Wrote final throughput report and manifest", flush=True)


if __name__ == "__main__":
    main()
