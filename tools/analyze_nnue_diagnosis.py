"""Recompute paired tournament statistics and offline position diagnostics."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
import itertools
import json
import math
from pathlib import Path
import random
import statistics

from tools.nnue_diagnosis import ROOT, SEED, save


def average(values: list[float]) -> float | None:
    return statistics.mean(values) if values else None


def quantile(values: list[float], p: float) -> float:
    ordered = sorted(values)
    index = (len(ordered) - 1) * p
    low = int(index)
    return ordered[low] + (ordered[min(low + 1, len(ordered) - 1)] - ordered[low]) * (index - low)


def interval(values: list[float]) -> list[float]:
    return [quantile(values, .025), quantile(values, .975)]


def bootstrap(values: list[float], repeats: int = 20000) -> list[float] | None:
    if not values:
        return None
    rng = random.Random(SEED)
    return interval([sum(rng.choices(values, k=len(values))) / len(values) for _ in range(repeats)])


def elo(score: float | None) -> float | None:
    # Null endpoints are unbounded, with direction determined by the score.
    return 400 * math.log10(score / (1 - score)) if score is not None and 0 < score < 1 else None


def pair_scores(games: list[dict]) -> dict[int, float]:
    pairs: dict[int, list[dict]] = defaultdict(list)
    for game in games:
        pairs[game["pair"]].append(game)
    points = {"win": 1., "draw": .5, "loss": 0.}
    return {pair: sum(points[g["candidate_outcome"]] for g in rows) / 2
            for pair, rows in pairs.items() if len(rows) == 2 and all(g["candidate_outcome"] in points for g in rows)}


def partial_pair_scores(games: list[dict]) -> dict[int, list[float]]:
    pairs: dict[int, list[dict]] = defaultdict(list)
    for game in games:
        pairs[game["pair"]].append(game)
    points = {"win": 1., "draw": .5, "loss": 0.}
    result = {}
    for pair, rows in pairs.items():
        assert len(rows) == 2
        known = sum(points.get(g["candidate_outcome"], 0) for g in rows)
        missing = sum(g["candidate_outcome"] == "unfinished" for g in rows)
        result[pair] = [known / 2, (known + missing) / 2]
    return result


def move_metrics(games: list[dict], candidate: bool) -> dict:
    rows = [s for game in games for s in game["searches"] if s["candidate"] == candidate]
    nodes = sum(s["nodes"] for s in rows)
    seconds = sum(s["seconds"] for s in rows)
    wall = sum(s["wall_seconds"] for s in rows)
    return {"moves": len(rows), "mean_completed_depth": average([s["depth"] for s in rows]),
            "median_completed_depth": statistics.median(s["depth"] for s in rows) if rows else None,
            "mean_nodes": average([s["nodes"] for s in rows]), "mean_reported_nps": average([s["nps"] for s in rows]),
            "aggregate_nps": nodes / seconds if seconds else None, "aggregate_wall_nps": nodes / wall if wall else None,
            "mean_engine_seconds": seconds / len(rows) if rows else None,
            "mean_wall_seconds": wall / len(rows) if rows else None, "total_nodes": nodes, "total_engine_seconds": seconds,
            "total_wall_seconds": wall}


def cohort(games: list[dict]) -> dict:
    counts = Counter(g["candidate_outcome"] for g in games)
    n = counts["win"] + counts["draw"] + counts["loss"]
    score = (counts["win"] + counts["draw"] / 2) / n if n else None
    pairs = pair_scores(games)
    paired_score = average(list(pairs.values()))
    ci = bootstrap(list(pairs.values()))
    margin = math.sqrt(math.log(40) / (2 * len(pairs))) if pairs else None
    conservative = [max(0, paired_score - margin), min(1, paired_score + margin)] if pairs else None
    finished_points = counts["win"] + counts["draw"] / 2
    partial = list(partial_pair_scores(games).values())
    rng = random.Random(SEED)
    draws = [rng.choices(partial, k=len(partial)) for _ in range(20000)]
    censoring_ci = [quantile([statistics.mean(v[0] for v in draw) for draw in draws], .025),
                    quantile([statistics.mean(v[1] for v in draw) for draw in draws], .975)]
    return {"games": len(games), "wins": counts["win"], "draws": counts["draw"], "losses": counts["loss"],
            "unfinished": counts["unfinished"], "score": score, "relative_elo": elo(score),
            "complete_pairs": len(pairs), "paired_score": paired_score, "paired_bootstrap_95": ci,
            "paired_elo_bootstrap_95": [elo(x) for x in ci] if ci else None,
            "paired_hoeffding_95": conservative,
            "unfinished_worst_best_score": [finished_points / len(games), (finished_points + counts["unfinished"]) / len(games)],
            "paired_censoring_bootstrap_95_envelope": censoring_ci,
            "termination_counts": dict(Counter(g["termination"] for g in games)),
            "game_wall_seconds": sum(g["wall_seconds"] for g in games),
            "nnue": move_metrics(games, True), "classical": move_metrics(games, False)}


def tournaments() -> dict:
    plan = json.loads((ROOT / "match-plan.json").read_text(encoding="utf-8"))
    data = {"method": "20,000 percentile bootstrap resamples of complete opening pairs, seed 20261017; both colors remain together. Complete-pair score intervals accompany all-completed-game WDL estimates. Also bounded-pair Hoeffding 95% intervals. Opening-family dependence, censoring and small samples limit nominal coverage. No optional stopping or extra games.", "full": {}, "matched_first_ten": {}}
    pair_maps, partial_maps = [], []
    records_by_time = {}
    book = json.loads(Path(plan["opening_book"]).read_text(encoding="utf-8"))["openings"]
    for match in plan["schedule"]:
        record = json.loads(Path(match["output"]).read_text(encoding="utf-8"))
        assert len(record["games"]) == match["games"]
        assert record["opening_book_sha256"] == plan["opening_book_sha256"]
        label = str(match["movetime"])
        records_by_time[label] = record
        data["full"][label] = cohort(record["games"]) | {"exploratory": match["exploratory"]}
        family_groups: dict[str, list[float]] = defaultdict(list)
        for pair, value in pair_scores(record["games"]).items():
            family_groups[book[pair - 1]["family"]].append(value)
        families = list(family_groups.values())
        rng = random.Random(SEED)
        family_samples = []
        for _ in range(20000):
            draw = rng.choices(families, k=len(families))
            family_samples.append(sum(map(sum, draw)) / sum(map(len, draw)))
        data["full"][label]["opening_family_cluster_bootstrap_95"] = interval(family_samples)
        common = [g for g in record["games"] if g["pair"] <= 10]
        data["matched_first_ten"][label] = cohort(common)
        pair_maps.append(pair_scores(common))
        partial_maps.append(partial_pair_scores(common))
    ids = sorted(set.intersection(*(set(pairs) for pairs in pair_maps)))
    assert ids, "No fully completed common pairs"
    data["matched_common_complete"] = {label: cohort([g for g in record["games"] if g["pair"] in ids])
                                       for label, record in records_by_time.items()}
    times = [m["movetime"] for m in plan["schedule"]]
    x = [math.log10(t) for t in times]
    xbar = statistics.mean(x)
    denom = sum((v - xbar) ** 2 for v in x)
    vectors = [[pairs[i] for pairs in pair_maps] for i in ids]
    means = [statistics.mean(v[j] for v in vectors) for j in range(4)]
    slope = lambda ys: sum((v - xbar) * y for v, y in zip(x, ys)) / denom
    deltas = [v[-1] - v[0] for v in vectors]
    observed = statistics.mean(deltas)
    rng = random.Random(SEED)
    samples = [[statistics.mean(v[j] for v in draw) for j in range(4)]
               for draw in (rng.choices(vectors, k=len(vectors)) for _ in range(20000))]
    # Exact paired sign-flip test for the prespecified 1000ms-minus-50ms contrast.
    flips = [abs(sum(sign * delta for sign, delta in zip(signs, deltas)) / len(deltas))
             for signs in itertools.product((-1, 1), repeat=len(deltas))]
    data["trend"] = {"common_complete_pair_ids": ids, "scores": dict(zip(map(str, times), means)),
                     "paired_score_vectors": dict(zip(map(str, ids), vectors)),
                     "endpoint_score_difference": observed,
                     "endpoint_bootstrap_95": interval([s[-1] - s[0] for s in samples]),
                     "slope_score_per_log10_ms": slope(means), "slope_bootstrap_95": interval([slope(s) for s in samples]),
                     "endpoint_two_sided_sign_flip_p": sum(v >= abs(observed) - 1e-12 for v in flips) / len(flips),
                     "test_limitations": "One prespecified endpoint contrast, whole-pair exchangeable symmetric differences assumed; observational time-control experiment with ten opening pairs. Percentile bootstrap is approximate, especially near endpoints. No universal Elo/time extrapolation."}
    # Primary all-ten analysis: keep every requested opening even if a game is
    # capped. Unknown outcomes range from zero to one; never impute a draw.
    all_ids = sorted(set.intersection(*(set(pairs) for pairs in partial_maps)))
    assert all_ids == list(range(1, 11))
    partial_vectors = [[pairs[i] for pairs in partial_maps] for i in all_ids]
    weights = [(v - xbar) / denom for v in x]
    def contrasts(draw: list[list[list[float]]]) -> tuple[float, float, float, float]:
        lower = [statistics.mean(v[j][0] for v in draw) for j in range(4)]
        upper = [statistics.mean(v[j][1] for v in draw) for j in range(4)]
        return (lower[-1] - upper[0], upper[-1] - lower[0],
                sum(w * (lo if w >= 0 else hi) for w, lo, hi in zip(weights, lower, upper)),
                sum(w * (hi if w >= 0 else lo) for w, lo, hi in zip(weights, lower, upper)))
    limits = contrasts(partial_vectors)
    rng = random.Random(SEED)
    resamples = [contrasts(rng.choices(partial_vectors, k=10)) for _ in range(20000)]
    data["all_ten_censoring_aware_trend"] = {"pair_ids": all_ids, "paired_score_bounds": partial_maps,
        "endpoint_score_difference_bounds": list(limits[:2]), "slope_bounds": list(limits[2:]),
        "endpoint_bootstrap_95_envelope": [quantile([r[0] for r in resamples], .025), quantile([r[1] for r in resamples], .975)],
        "slope_bootstrap_95_envelope": [quantile([r[2] for r in resamples], .025), quantile([r[3] for r in resamples], .975)],
        "method": "All ten opening pairs at all four controls, jointly resampled by pair. Every capped game's unknown points range [0,1]. Envelopes combine percentile sampling variability with worst/best unknown outcomes; approximate sensitivity envelopes, not proof of 95% coverage under arbitrary censoring. Complete-case results are supplementary."}
    save(ROOT / "tournament-summary.json", data)
    with (ROOT / "tournament-summary.csv").open("w", newline="", encoding="utf-8") as stream:
        columns = ["cohort", "ms", "games", "wins", "draws", "losses", "unfinished", "score", "relative_elo", "complete_pairs"]
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for group in ("full", "matched_first_ten"):
            for ms, row in data[group].items():
                writer.writerow({"cohort": group, "ms": ms, **{k: row[k] for k in columns[2:]}})
    return data


def sigmoid(cp: float) -> float:
    return 1 / (1 + math.exp(-max(-20000, min(20000, cp)) / 400))


def reference_rank(result: dict) -> tuple[float, float]:
    """Order finite, mate and terminal scores without assigning fake CP to mate."""
    if result.get("root_points") is not None:
        return (2, 0) if result["root_points"] == 1 else (-2, 0) if result["root_points"] == 0 else (0, 0)
    cp, mate = result["score_root"]["cp"], result["score_root"]["mate"]
    if mate is not None:
        return (1 if mate > 0 else -1, -mate)
    return (0, cp)


def candidate_quality(reference: dict, move: str) -> dict:
    chosen = reference["candidates"][move]
    best_move = reference["root"]["move"]
    baseline = reference["candidates"][best_move]
    cp, best_cp = chosen["score_root"]["cp"], baseline["score_root"]["cp"]
    raw = best_cp - cp if cp is not None and best_cp is not None else None
    result = {"sf_best_agreement": move == best_move, "raw_child_loss_cp": raw,
              "loss_cp": max(0, raw) if raw is not None else None,
              "probability_transformed_loss": max(0, sigmoid(best_cp) - sigmoid(cp)) if raw is not None else None,
              "candidate_score_root": chosen["score_root"], "reference_child_score_root": baseline["score_root"],
              "terminal": chosen.get("terminal"), "root_points": chosen.get("root_points")}
    root_mate = reference["root"]["score_root"]["mate"]
    child_mate = chosen["score_root"]["mate"]
    result["reference_winning_mate_not_reported"] = bool(root_mate is not None and root_mate > 0 and
                                                       not (child_mate is not None and child_mate > 0) and chosen.get("root_points") != 1)
    return result


def stability(record: dict) -> dict:
    iterations = record["iterations"]
    moves = [i["pv"][0] if i["pv"] else None for i in iterations]
    scores = [i["score_white"]["cp"] for i in iterations]
    swings = [abs(a - b) for a, b in zip(scores, scores[1:]) if a is not None and b is not None]
    return {"completed_iterations": len(iterations), "best_move_changes": sum(a != b for a, b in zip(moves, moves[1:])),
            "max_adjacent_score_swing_cp": max(swings, default=0), "depth_moves": list(zip([i["depth"] for i in iterations], moves)),
            "aspiration_retries": record["counters"].get("aspiration_retries", 0),
            "pvs_researches": record["counters"].get("researches", 0), "lmr_researches": record["counters"].get("lmr_researches", 0),
            "qnode_fraction": record["counters"].get("qnodes", 0) / max(1, record["nodes"])}


def throughput() -> dict:
    source = json.loads((ROOT / "controlled-searches.json").read_text(encoding="utf-8"))
    suite = {r["id"]: r for r in json.loads((ROOT / "positions.json").read_text(encoding="utf-8"))["positions"]}
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for r in source["records"]:
        groups[(r["position"], r["mode"], r["budget"], r["evaluator"])].append(r)
    pairs, aggregates = [], []
    keys = sorted({key[:3] for key in groups})
    for position, mode, budget in keys:
        samples = {e: groups[(position, mode, budget, e)] for e in ("nnue", "classical")}
        medians = {e: {key: statistics.median(r[key] for r in rows) for key in ("nodes", "depth", "nps", "wall_seconds", "seconds", "seldepth")} for e, rows in samples.items()}
        eligible = not suite[position]["short_forced_fixture"] and all(m["seconds"] >= .01 for m in medians.values())
        pairs.append({"position": position, "category": suite[position]["category"], "mode": mode, "budget": budget,
                      "eligible_for_nps_aggregate": eligible, "medians": medians,
                      "nps_ratio": medians["nnue"]["nps"] / max(1, medians["classical"]["nps"]),
                      "depth_difference": medians["nnue"]["depth"] - medians["classical"]["depth"],
                      "repeat_move_counts": {e: dict(Counter(r["move"] for r in rows)) for e, rows in samples.items()},
                      "nps_repeat_range": {e: [min(r["nps"] for r in rows), max(r["nps"] for r in rows)] for e, rows in samples.items()}})
    for mode, budget in sorted({(r["mode"], r["budget"]) for r in pairs}):
        rows = [r for r in pairs if r["mode"] == mode and r["budget"] == budget]
        eligible = [r for r in rows if r["eligible_for_nps_aggregate"]]
        aggregates.append({"mode": mode, "budget": budget, "positions": len(rows), "nps_positions": len(eligible),
                           "geometric_mean_nps_ratio": math.exp(statistics.mean(math.log(r["nps_ratio"]) for r in eligible)) if eligible else None,
                           "mean_depth_difference": average([r["depth_difference"] for r in rows]),
                           "nnue_mean_nodes": average([r["medians"]["nnue"]["nodes"] for r in rows]),
                           "classical_mean_nodes": average([r["medians"]["classical"]["nodes"] for r in rows]),
                           "nnue_mean_wall_seconds": average([r["medians"]["nnue"]["wall_seconds"] for r in rows]),
                           "classical_mean_wall_seconds": average([r["medians"]["classical"]["wall_seconds"] for r in rows])})
    data = {"method": "Median of three trials per evaluator/FEN/budget, geometric mean of per-FEN NPS ratios. Excludes two short mate fixtures and sub-10ms measurements from NPS aggregate only. Search-tree composition differs by evaluator; this is whole-search throughput, not isolated head speed. All requested categories remain in decision/depth analyses.", "summary": aggregates, "positions": pairs}
    save(ROOT / "throughput-summary.json", data)
    return data


def position_analysis() -> dict:
    positions = {r["id"]: r for r in json.loads((ROOT / "positions.json").read_text(encoding="utf-8"))["positions"]}
    reference = {r["position"]: r for r in json.loads((ROOT / "stockfish-quality.json").read_text(encoding="utf-8"))["records"]}
    sources = {name: json.loads((ROOT / file).read_text(encoding="utf-8"))["records"]
               for name, file in (("controlled", "controlled-searches.json"), ("ablation", "ablations.json"))}
    detailed = []
    for experiment, records in sources.items():
        for r in records:
            if r["repeat"]:
                continue  # Quality uses the prespecified first trial, not repeated pseudo-samples.
            detailed.append({key: r[key] for key in ("position", "configuration", "evaluator", "mode", "budget", "depth", "nodes", "nps", "wall_seconds", "move", "pv", "score_white", "counters")} |
                            {"experiment": experiment, "category": positions[r["position"]]["category"],
                             "quality": candidate_quality(reference[r["position"]], r["move"]), "stability": stability(r)})
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for r in detailed:
        groups[(r["experiment"], r["configuration"], r["mode"], r["budget"], r["evaluator"])].append(r)
    summary = []
    for key, rows in groups.items():
        cp = [r["quality"]["loss_cp"] for r in rows if r["quality"]["loss_cp"] is not None]
        summary.append(dict(zip(("experiment", "configuration", "mode", "budget", "evaluator"), key)) |
                       {"positions": len(rows), "cp_comparable": len(cp), "mean_loss_cp": average(cp),
                        "median_loss_cp": statistics.median(cp) if cp else None,
                        "large_100cp": sum(v >= 100 for v in cp), "large_300cp": sum(v >= 300 for v in cp),
                        "negative_raw_losses": sum(r["quality"]["raw_child_loss_cp"] is not None and r["quality"]["raw_child_loss_cp"] < 0 for r in rows),
                        "sf_best_agreement": sum(r["quality"]["sf_best_agreement"] for r in rows),
                        "reference_winning_mate_not_reported": sum(r["quality"]["reference_winning_mate_not_reported"] for r in rows),
                        "mean_probability_loss": average([r["quality"]["probability_transformed_loss"] for r in rows if r["quality"]["probability_transformed_loss"] is not None]),
                        "mean_depth": average([r["depth"] for r in rows]), "mean_nodes": average([r["nodes"] for r in rows]),
                        "mean_best_move_changes": average([r["stability"]["best_move_changes"] for r in rows])})
    agreements, comparisons = [], []
    paired: dict[tuple, dict] = defaultdict(dict)
    for r in detailed:
        paired[(r["experiment"], r["configuration"], r["mode"], r["budget"], r["position"])][r["evaluator"]] = r
    for key, both in paired.items():
        nn, cl = both["nnue"], both["classical"]
        ncp, ccp = nn["quality"]["loss_cp"], cl["quality"]["loss_cp"]
        ref = reference[key[-1]]["candidates"]
        ns, cs = ref[nn["move"]], ref[cl["move"]]
        raw_ncp, raw_ccp = ns["score_root"]["cp"], cs["score_root"]["cp"]
        preference = (reference_rank(ns) > reference_rank(cs)) - (reference_rank(ns) < reference_rank(cs))
        comparisons.append(dict(zip(("experiment", "configuration", "mode", "budget", "position"), key)) |
                           {"category": nn["category"], "same_move": nn["move"] == cl["move"],
                            "nnue_move": nn["move"], "classical_move": cl["move"],
                            "nnue_minus_classical_loss_cp": ncp - ccp if ncp is not None and ccp is not None else None,
                            "direct_classical_minus_nnue_child_cp": raw_ccp - raw_ncp if raw_ncp is not None and raw_ccp is not None else None,
                            "reference_preference_nnue": preference,
                            "nnue_quality": nn["quality"], "classical_quality": cl["quality"]})
    contrast_groups: dict[tuple, list[dict]] = defaultdict(list)
    for r in comparisons:
        contrast_groups[(r["experiment"], r["configuration"], r["mode"], r["budget"])].append(r)
    for key, rows in contrast_groups.items():
        losses = [r["nnue_minus_classical_loss_cp"] for r in rows if r["nnue_minus_classical_loss_cp"] is not None]
        direct = [r["direct_classical_minus_nnue_child_cp"] for r in rows if r["direct_classical_minus_nnue_child_cp"] is not None]
        agreements.append(dict(zip(("experiment", "configuration", "mode", "budget"), key)) |
                          {"same_move": sum(r["same_move"] for r in rows), "positions": len(rows),
                           "paired_cp_positions": len(losses), "mean_nnue_minus_classical_loss_cp": average(losses),
                           "paired_position_bootstrap_95": bootstrap(losses),
                           "direct_cp_positions": len(direct), "mean_direct_classical_minus_nnue_child_cp": average(direct),
                           "direct_paired_position_bootstrap_95": bootstrap(direct),
                           "reference_prefers_nnue": sum(r["reference_preference_nnue"] > 0 for r in rows),
                           "reference_prefers_classical": sum(r["reference_preference_nnue"] < 0 for r in rows),
                           "nnue_worse": sum(v > 0 for v in losses), "nnue_better": sum(v < 0 for v in losses)})
    ablation_effects = []
    lookup = {(r["position"], r["evaluator"], r["mode"], r["budget"], r["configuration"]): r
              for r in detailed if r["experiment"] == "ablation"}
    for configuration in ("no_lmr", "no_null", "no_futility", "no_reverse_futility", "no_aspiration"):
        for evaluator in ("nnue", "classical"):
            for mode, budget in (("time", 200), ("nodes", 100000)):
                pairs = [(lookup[(position, evaluator, mode, budget, "production")], lookup[(position, evaluator, mode, budget, configuration)]) for position in positions]
                loss_changes = [b["quality"]["loss_cp"] - a["quality"]["loss_cp"] for a, b in pairs if a["quality"]["loss_cp"] is not None and b["quality"]["loss_cp"] is not None]
                ablation_effects.append({"configuration": configuration, "evaluator": evaluator, "mode": mode, "budget": budget,
                                        "move_changes": sum(a["move"] != b["move"] for a, b in pairs),
                                        "pv_changes": sum(a["pv"] != b["pv"] for a, b in pairs),
                                        "mean_loss_cp_change": average(loss_changes), "paired_cp_positions": len(loss_changes),
                                        "loss_change_bootstrap_95": bootstrap(loss_changes),
                                        "mean_depth_change": average([b["depth"] - a["depth"] for a, b in pairs]),
                                        "mean_nodes_change": average([b["nodes"] - a["nodes"] for a, b in pairs]),
                                        "mean_stability_changes": average([b["stability"]["best_move_changes"] - a["stability"]["best_move_changes"] for a, b in pairs]),
                                        "reference_winning_mate_change": sum(b["quality"]["reference_winning_mate_not_reported"] - a["quality"]["reference_winning_mate_not_reported"] for a, b in pairs)})
    data = {"method": "Quality uses first repetition only; repeats characterize speed/stability. Child-vs-child SF300k estimates, root side-to-move perspective. Mate/nonmate mixed comparisons excluded from CP aggregates. Approximate paired-position bootstrap intervals on hand-selected examples are exploratory; no Elo interpretation.",
            "summary": summary, "evaluator_comparisons": agreements, "comparisons": comparisons,
            "ablation_effects": ablation_effects, "details": detailed}
    save(ROOT / "position-summary.json", data)
    with (ROOT / "position-summary.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(summary[0]))
        writer.writeheader(); writer.writerows(summary)
    save(ROOT / "search-stability.json", {"method": "Published completed-iteration PVs; repeated choices and score swings are descriptive. A changed PV alone is not a tactical failure.", "records": detailed})
    return data


def plots(data: dict) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    times = [50, 200, 500, 1000]
    matched = [data["matched_first_ten"][str(t)] for t in times]
    fig, axes = plt.subplots(2, 3, figsize=(14, 8), layout="constrained")
    for ax in axes.flat:
        ax.set_xscale("log"); ax.set_xticks(times, labels=times); ax.set_xlabel("Requested ms/move"); ax.grid(alpha=.25)
    scores = [r["paired_score"] * 100 if not r["unfinished"] else float("nan") for r in matched]
    ci = [r["paired_censoring_bootstrap_95_envelope"] for r in matched]
    axes[0, 0].plot(times, scores, marker="o")
    for t, row, bounds in zip(times, matched, ci):
        axes[0, 0].vlines(t, bounds[0] * 100, bounds[1] * 100, color="steelblue", linewidth=2)
        if row["unfinished"]:
            lo, hi = row["unfinished_worst_best_score"]
            axes[0, 0].vlines(t, lo * 100, hi * 100, color="black", linewidth=5)
    axes[0, 0].axhline(50, color="gray", linestyle="--"); axes[0, 0].set_title("NNUE score: same first 10 pairs"); axes[0, 0].set_ylabel("Score (%) / paired bootstrap 95%")
    axes[0, 1].plot(times, [elo(r["paired_score"]) if not r["unfinished"] else float("nan") for r in matched], marker="o"); axes[0, 1].axhline(0, color="gray", linestyle="--"); axes[0, 1].set_title("Matched relative Elo (capped point omitted)")
    axes[0, 2].plot(times, [r["nnue"]["aggregate_nps"] / r["classical"]["aggregate_nps"] for r in matched], marker="o"); axes[0, 2].set_title("Matched-game NNUE / classical NPS")
    axes[1, 0].plot(times, [r["nnue"]["mean_completed_depth"] - r["classical"]["mean_completed_depth"] for r in matched], marker="o"); axes[1, 0].set_title("Mean completed-depth difference")
    for label in ("nnue", "classical"):
        axes[1, 1].plot(times, [r[label]["mean_nodes"] for r in matched], marker="o", label=label)
    axes[1, 1].legend(); axes[1, 1].set_title("Mean searched nodes per move")
    axes[1, 2].axis("off")
    trend = data["all_ten_censoring_aware_trend"]
    axes[1, 2].text(0, .9, "Same 10 opening pairs, reversed colors\n500ms and 1000ms: exploratory\nBlue bars: paired bootstrap/censoring envelope\nBlack bars: possible score for capped games\nCapped scores have no point estimate\nGame NPS reflects different positions\n\n1000ms − 50ms score difference:\n" + f"{trend['endpoint_score_difference_bounds'][0] * 100:+.1f} to {trend['endpoint_score_difference_bounds'][1] * 100:+.1f} percentage points\n95% sensitivity envelope:\n{trend['endpoint_bootstrap_95_envelope'][0] * 100:+.1f} to {trend['endpoint_bootstrap_95_envelope'][1] * 100:+.1f}", va="top", transform=axes[1, 2].transAxes)
    fig.suptitle("Compact v2 diagnosis — matched time-control trend")
    fig.savefig(ROOT / "matched-trends.png", dpi=160)
    fig.savefig(ROOT / "matched-trends.svg")
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("tournaments", "positions", "all"), default="all")
    parser.add_argument("--plots", action="store_true")
    args = parser.parse_args()
    if args.phase in ("tournaments", "all"):
        data = tournaments()
        if args.plots:
            plots(data)
    if args.phase in ("positions", "all"):
        position_analysis()
        throughput()


if __name__ == "__main__":
    main()
