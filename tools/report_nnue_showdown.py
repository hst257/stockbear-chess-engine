"""Analyze the fixed showdown without loading training/test data or an engine."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime
import itertools
import math
from pathlib import Path
import random
import statistics

import chess
import chess.pgn

from tools.nnue_showdown import (REPO, DEFAULT_ROOT, MODELS, load, save, sha, records,
                                 points, stats, standings, select_finalists, utc, validate_identity)
from tools.run_nnue_showdown_amended import scope


def paired_uncertainty(rows: list[dict], label: str) -> dict:
    grouped = defaultdict(list)
    for record in rows:
        grouped[record["game"]["opening"]].append(record)
    pairs = []
    for opening in sorted(grouped):
        group = grouped[opening]
        values = [points(r, label) for r in group]
        if len(group) == 2 and None not in values:
            pairs.append(sum(values) / 2)
    if not pairs:
        return {"complete_pairs": 0, "paired_score": None, "hoeffding_95": [0., 1.], "bootstrap_95": [0., 1.]}
    mean = statistics.mean(pairs)
    bound = math.sqrt(math.log(40) / (2 * len(pairs)))
    rng = random.Random(20261016)
    boot = sorted(statistics.mean(rng.choices(pairs, k=len(pairs))) for _ in range(5000))
    return {"complete_pairs": len(pairs), "pair_scores": pairs, "paired_score": mean,
            "hoeffding_95": [max(0., mean - bound), min(1., mean + bound)],
            "bootstrap_95": [boot[124], boot[4874]],
            "note": "Nominal independent opening pairs, both colors clustered; bootstrap is descriptive and can degenerate. Hoeffding is the conservative primary bound; fixed hand-selected opening suite limits population inference."}


def matched_roots(rows: list[dict]) -> dict:
    groups = defaultdict(lambda: defaultdict(list))
    for record in rows:
        if record["searches"]:
            first = record["searches"][0]
            groups[record["game"]["opening"]][first["engine"]].append(first)
    per_model = {}
    for label in MODELS:
        moves = [s for models in groups.values() for s in models[label]]
        if moves:
            seconds = sum(s["engine_seconds"] for s in moves)
            per_model[label] = {"root_searches": len(moves), "nps": sum(s["nodes"] for s in moves) / seconds,
                                "mean_depth": statistics.mean(s["depth"] for s in moves),
                                "median_depth": statistics.median(s["depth"] for s in moves)}
    ratios = {}
    for a, b in itertools.combinations(MODELS, 2):
        values, depth_differences = [], []
        for opening, models in groups.items():
            if models[a] and models[b]:
                def speed(items):
                    return sum(s["nodes"] for s in items) / sum(s["engine_seconds"] for s in items)
                values.append(speed(models[b]) / speed(models[a]))
                depth_differences.append(statistics.mean(s["depth"] for s in models[b]) - statistics.mean(s["depth"] for s in models[a]))
        if values:
            ratios[f"{b}/{a}"] = {"opening_positions": len(values),
                                    "geometric_nps_ratio": math.exp(statistics.mean(math.log(v) for v in values)),
                                    "mean_depth_difference": statistics.mean(depth_differences)}
    return {"models": per_model, "matched_comparisons": ratios,
            "method": "First searched move in each game, grouped by identical opening FEN and time; every model starts from the same board/history with fresh processes. No extra engine searches."}


def audit(root: Path, plan: dict, rows: list[dict], complete: bool) -> dict:
    validate_identity(root, plan)
    amended = (root / "schedule-amendment.json").exists()
    expected = {g["id"]: g for g in (scope(root)[1] if amended else plan["schedule"])}
    if (root / "finalists.json").exists():
        final = load(root / "finalists.json")
        assert final["plan_sha256"] == sha(root / "plan.json")
        assert final["finalists"] == select_finalists(rows)
        expected.update({g["id"]: g for g in final["schedule"]})
    moves, overruns = 0, []
    for record in rows:
        game = record["game"]
        assert game == expected[game["id"]] and record["plan_sha256"] == sha(root / "plan.json")
        board = chess.Board()
        for move in plan["openings"][game["opening"]]["moves"]:
            board.push_uci(move)
        for row in record["searches"]:
            assert row["engine"] == (game["white"] if board.turn else game["black"])
            board.push_uci(row["move"])
            assert row["nodes"] >= 0 and row["nnue_evaluations"] == row["eval_calls"]
            if row["wall_seconds"] > game["ms"] / 1000 + plan["allowance_seconds"]:
                overruns.append({"game": game["id"], "seconds": row["wall_seconds"]})
            moves += 1
        outcome = board.outcome(claim_draw=True)
        assert record["result"] == (outcome.result() if outcome else "*")
        assert board.fen() == record["final_fen"]
        with (root / "games" / (game["id"] + ".pgn")).open(encoding="utf-8") as stream:
            pgn = chess.pgn.read_game(stream)
            assert pgn and not pgn.errors and pgn.headers["Result"] == record["result"]
            assert list(pgn.mainline_moves()) == board.move_stack
    if complete:
        assert len(rows) == len(expected) == (108 if amended else 130)
        assert {r["game"]["id"] for r in rows} == set(expected)
    assert not overruns
    preserved = load(root / "preservation-before.json")
    changed = [name for name, checksum in preserved.items() if sha(REPO / name) != checksum]
    result = {"checked_utc": utc(), "games": len(rows), "searched_moves": moves,
              "overruns": overruns, "protected_files": len(preserved), "changed_protected_files": changed,
              "test_dataset_opened": False, "passed": not changed and not overruns}
    save(root / "audit.json", result)
    if changed:
        raise ValueError("Protected engine/model/checkpoint changed")
    return result


def analyze(root: Path, require_complete: bool = True) -> dict:
    plan = load(root / "plan.json")
    scope(root)  # Reject an unrelated plan or any omitted-control records.
    rows = records(root)
    verified = audit(root, plan, rows, require_complete)
    failures = [load(p) for p in sorted((root / "failures").glob("*.json"))]
    formats = {}
    for ms in (500, 1000):
        cohort = [r for r in rows if r["game"]["ms"] == ms]
        pairs = {}
        for a, b in itertools.combinations(MODELS, 2):
            pair = [r for r in cohort if set(r["game"]["pair"]) == {a, b}]
            if pair:
                left, right = stats(pair, a), stats(pair, b)
                pairs[f"{a}-{b}"] = {"first": a, "second": b, "first_stats": left, "second_stats": right,
                    "relative_nps_second_vs_first_percent": 100 * (right["aggregate_nps"] / left["aggregate_nps"] - 1),
                    "uncertainty_first": paired_uncertainty(pair, a)}
        formats[str(ms)] = {"games": len(cohort), "models": {n: stats(cohort, n) for n in MODELS if any(n in r["game"]["pair"] for r in cohort)},
                            "pairs": pairs, "matched_roots": matched_roots(cohort), "exploratory": ms == 1000}
    ranking = standings(rows)
    for row in ranking:
        row["formats"].pop("3000", None)
        scores = [row["formats"][str(ms)]["score_fraction"] for ms in (500, 1000)]
        row["equal_format_score"] = statistics.mean(scores) if None not in scores else None
        tied = [r["model"] for r in ranking if all(
            r["formats"][str(ms)]["score_fraction"] is not None for ms in (500, 1000))
            and statistics.mean(r["formats"][str(ms)]["score_fraction"] for ms in (500, 1000)) == row["equal_format_score"]]
        mini = [stats([g for g in rows if g["game"]["ms"] == ms and all(n in tied for n in g["game"]["pair"])], row["model"])["score_fraction"]
                for ms in (500, 1000)]
        row["tied_mini_league_score"] = statistics.mean(mini) if None not in mini else None
    ranking.sort(key=lambda r: (-(r["equal_format_score"] or 0), -(r["tied_mini_league_score"] or 0), int(r["model"])))
    result = {"generated_utc": utc(), "plan_sha256": sha(root / "plan.json"), "completed_games": len(rows),
              "formats": formats, "round_robin_standings": ranking, "failures": failures,
              "schedule_amendment": load(root / "schedule-amendment.json"),
              "terminations": dict(Counter(r["termination"] for r in rows)), "audit": verified,
              "finalists": load(root / "finalists.json") if (root / "finalists.json").exists() else None}
    result["shared_first_six_pairs"] = {
        str(ms): {f"{a}-{b}": stats([r for r in rows if r["game"]["ms"] == ms and r["game"]["opening"] < 6
                                    and set(r["game"]["pair"]) == {a, b}], a)
                  for a, b in itertools.combinations(MODELS, 2)} for ms in (500, 1000)}
    if rows:
        first = min(datetime.fromisoformat(r["started_utc"]) for r in rows)
        last = max(datetime.fromisoformat(r["completed_utc"]) for r in rows)
        result["elapsed_wall_seconds_first_to_last_game"] = (last - first).total_seconds()
    result["failures_by_kind"] = dict(Counter(f["kind"] for f in failures))
    save(root / "analysis.json", result)
    if require_complete:
        report(root, plan, result, rows)
    return result


def pct(value):
    return "—" if value is None else f"{100*value:.1f}%"


def report(root: Path, plan: dict, result: dict, rows: list[dict]) -> None:
    ranking = result["round_robin_standings"]
    candidate = ranking[0]["model"]
    lines = ["# StockBear NNUE Architecture Showdown", "", "## Result and recommendation", "",
        f"The equal-weight ranking across the two retained controls selects **{candidate}** as the leading candidate for a future classical match. "
        "The winner remains uncertain: the small fixed opening suite and broad paired-opening intervals do not establish a definitive strength difference. "
        "No Elo estimate pools time controls, and validation MSE is not used to rank chess results.", "",
        "## Configuration and fairness", "",
        f"Completed {len(rows)}/108 games: 72 at 500 ms and 36 at 1000 ms. During the 1-second cohort, the user "
        "requested: ‘skip the 3s matchups, i think upto 1s will be enough’. The 18 scheduled 3-second games and four "
        "5-second final games were omitted before either cohort began. The original signed plan is retained alongside "
        "`schedule-amendment.json`; this was a user runtime amendment, not a result-driven automatic extension. "
        "Three pairings at each retained control; no extra classical matches, "
        "training, relabeling or test-set access. All matches ran sequentially, with no training or intensive benchmarks alongside them.", "",
        "The three isolated `-O2` C++17 binaries share unchanged search sources/flags, alpha-beta/PVS, move ordering, "
        "pruning, 16 MiB hash, one search worker, float32 `scalar` NNUE and incremental accumulators. No pondering. "
        "Only embedded architecture/weights differ. The active StockBear installation and classical evaluator remain unchanged.", "",
        "Twelve established opening main lines were shuffled with seed 20261016; no engine selected or filtered them. "
        "All pairings use the same first 12/6 opening pairs at 500/1000 ms, with reversed colors. "
        "Pairing order rotates; first-color order alternates across openings. "
        "Long-control samples are nested, not independent samples with which to infer a time trend from unmatched totals.", "",
        "Fresh processes reset game state. Full opening/move history is sent to UCI. Python-chess automatically claims "
        "available threefold/50-move draws and enforces checkmate, stalemate, insufficient material, fivefold and 75-move draws. "
        "No score-based win/draw adjudication or resignation. A 400-searched-ply cap is unfinished/unscored. "
        "The wall deadline is movetime plus 100 ms of protocol/OS allowance; engine and wall thinking times are saved separately.", "",
        "The original equal-format ranking rule is applied to the two retained controls: the mean of each model's "
        "500 ms and 1000 ms score fractions; tied groups use their equal-format head-to-head mini-league, then fewer parameters. "
        "The combined point total below is descriptive and weights the larger 500 ms cohort more heavily; it is not the selection score.", "",
        "## Engine and network identities", "", "| Model | Dimensions | Engine SHA-256 | Network SHA-256 |", "|---|---|---|---|"]
    for label in MODELS:
        e = plan["engines"][label]
        lines.append(f"| {e['name']} | {e['width']}/{e['hidden']} | `{e['sha256']}` | `{e['network_sha256']}` |")
    lines += ["", "Sources, flags, network/checkpoint provenance and exact paths are frozen in `plan.json` and the scaling "
        "experiment manifest. Actual UCI network identity/dimensions/kernel were checked before each new game, and binary/network/source "
        "hashes before every scheduled game and resume. All three passed 38 relevant existing regressions each; six core harness "
        "tests verified pairing, scoring, interruption/resume, missing-PGN recovery and unscored failure handling. "
        "Two additional amendment tests verified the 108-game boundary, no-op completion, and rejection of changed plans or omitted games. "
        "Preflight timed checks covered 500/1000/3000/5000 ms; special rules, terminal positions, incremental/rebuild equivalence, "
        "repetition, perft and completed-depth snapshots were verified.", "", "## Combined round-robin scoreboard", "",
        "| Model | W / D / L | Points / scored games | Raw score | Equal-format score |", "|---|---:|---:|---:|---:|"]
    for row in ranking:
        s = row["round_robin"]
        scored = s["games"] - s["unfinished"]
        lines.append(f"| {row['model']} | {s['wins']} / {s['draws']} / {s['losses']} | {s['points']:g} / {scored} | "
                     f"{pct(s['score_fraction'])} | {pct(row['equal_format_score'])} |")
    lines += ["", "## Per-format head-to-head results", "",
        "W/D/L and score refer to the first model. NPS is total nodes divided by engine-reported search seconds, "
        "including interrupted deeper-iteration work. It is a time-weighted aggregate, not the isolated inference benchmark. "
        "The NPS percentage is second-versus-first. Depth is the deepest completed iteration, not selective depth."]
    for ms, cohort in result["formats"].items():
        lines += ["", f"### {int(ms)/1000:g} seconds per move" + (" — exploratory" if cohort["exploratory"] else ""), "",
                  "| Pair | W / D / L | Points | Score | NPS first / second | NPS Δ second | Mean depth first / second | Paired 95% bound |",
                  "|---|---:|---:|---:|---:|---:|---:|---:|"]
        for pair, item in cohort["pairs"].items():
            a, b, ci = item["first_stats"], item["second_stats"], item["uncertainty_first"]
            lo, hi = ci["hoeffding_95"]
            lines.append(f"| {pair} | {a['wins']} / {a['draws']} / {a['losses']} | {a['points']:g} | {pct(a['score_fraction'])} | "
                f"{a['aggregate_nps']:,.0f} / {b['aggregate_nps']:,.0f} | {item['relative_nps_second_vs_first_percent']:+.1f}% | "
                f"{a['mean_depth']:.2f} / {b['mean_depth']:.2f} | {100*lo:.1f}–{100*hi:.1f}% ({ci['complete_pairs']} pairs) |")
        relevant = [f for f in result["failures"] if f["game"]["ms"] == int(ms)]
        lines += ["", "Failure events in this format: " + str(dict(Counter(f["kind"] for f in relevant))) +
                  ". All saved failure events are unscored and listed separately from chess results."]
        lines += ["", "| Model | Mean / median depth | Mean engine / wall move time (s) | Max wall time (s) | NNUE calls |",
                  "|---|---:|---:|---:|---:|"]
        for label, s in cohort["models"].items():
            lines.append(f"| {label} | {s['mean_depth']:.2f} / {s['median_depth']:g} | "
                         f"{s['mean_engine_seconds']:.4f} / {s['mean_wall_seconds']:.4f} | {s['max_wall_seconds']:.4f} | {s['nnue_evaluations']:,} |")
    lines += ["", "## Search-speed cost on matched opening roots", "",
        "Whole-game NPS/depth can change with the positions an evaluator chooses. To reduce that confounding, the "
        "following reuses the first searched move of each game: identical opening FEN/history, same budget, fresh engine. "
        "Each model has repeated root samples against both opponents. Ratios are geometric means over matched opening IDs. "
        "No additional searches were run.", "",
        "| Time (ms) | Ratio | Matched roots | NPS ratio | Mean completed-depth difference |", "|---|---|---:|---:|---:|"]
    for ms, cohort in result["formats"].items():
        for pair, r in cohort["matched_roots"]["matched_comparisons"].items():
            lines.append(f"| {ms} | {pair} | {r['opening_positions']} | {r['geometric_nps_ratio']:.3f}× | {r['mean_depth_difference']:+.2f} |")
    lines += ["", "NPS differences measure full search using different evaluators and therefore different trees. "
        "Even matched-root figures cannot isolate only the arithmetic cost of inference. Depth is a coarse, selective "
        "search measure and is not chess strength by itself. The earlier scaling microbenchmarks remain separate evidence. "
        "Existing release counters provide evaluation calls; accumulator-update/full-refresh counters are unavailable and "
        "were not inferred or enabled through a heavier diagnostic build.", "", "## Uncertainty and time-control interpretation", "",
        "Each uncertainty unit is an opening pair with colors together. The table uses the conservative 95% Hoeffding "
        "bounded-pair interval. Descriptive 5,000-resample paired-bootstrap intervals are also saved in `analysis.json`; "
        "they can be degenerate in tiny or unanimous samples. Neither method eliminates selection bias, dependence "
        "between related positions or fixed-suite limitations. The 1-second cohort has only six opening pairs per pairing "
        "and is exploratory; close scores do not establish definitive Elo differences.", "",
        "Cross-control trends compare the shared first six round-robin opening pairs. All per-format results stand separately; "
        "there is no pooled Elo estimate or automatic extension based on outcomes.", "",
        "| Pair (score for first model) | Same first 6 pairs: 500 ms | 1000 ms |", "|---|---:|---:|"]
    for a, b in itertools.combinations(MODELS, 2):
        lines.append(f"| {a}-{b} | " + " | ".join(pct(result["shared_first_six_pairs"][str(ms)][f"{a}-{b}"]["score_fraction"])
                                                     for ms in (500, 1000)) + " |")
    lines += ["", "These matched trend cells contain just twelve games each and remain exploratory. Per-format "
        "round-robin score leaders are: " + "; ".join(
            f"{ms} ms: " + ", ".join(n for n, s in cohort["models"].items()
                  if s["score_fraction"] == max(v["score_fraction"] for v in cohort["models"].values()))
            for ms, cohort in result["formats"].items()) + ".", "",
        "## Failures, adjudications and preservation", "",
        f"Termination counts: `{result['terminations']}`. Saved failure events: **{len(result['failures'])}**. "
        f"Final replay audit checked **{result['audit']['searched_moves']:,} searched moves**, PGNs, plan identities, legal results "
        f"and deadlines. **{result['audit']['protected_files']} protected files** were unchanged. "
        "Failures, if any, are recorded individually in `failures/` and are unscored; completed chess results are not silently "
        "replaced by infrastructure forfeits. In-progress move checkpoints and all completed games are retained. "
        "To apply the user amendment, G099 was interrupted after 43 saved searched moves and resumed from its legal full move history. "
        "Its new processes started with cold transient search caches; that single game's restart is a minor fairness limitation. "
        "The first resume attempt stalled before engine startup under restricted subprocess access and was stopped without changing moves; "
        "the successful resume used the same verified binaries and weights. No completed games were replayed. "
        f"Elapsed wall time from first game start to last completion: {result['elapsed_wall_seconds_first_to_last_game']/3600:.2f} hours "
        "(includes pauses between runner invocations).", "",
        "## Artifacts and reproduction", "",
        f"Experiment directory: `{root}`. `plan.json` freezes every opening FEN/identifier, engine/network hash, "
        "search option and game schedule. `games/Gxxx.json` and matching PGNs retain each game and per-move statistics. "
        "`schedule-amendment.json` records the shortened scope; `scoreboard.json`, `analysis.json`, `verification.json` "
        "and `audit.json` retain progress and validation. Binaries/build logs and runner output are under `artifacts/`.", "",
        "```powershell", r"Set-Location Z:\Code\Chess",
        r".\.venv\Scripts\python.exe -m tools.run_nnue_showdown_amended progress",
        r".\.venv\Scripts\python.exe -u -m tools.run_nnue_showdown_amended run",
        r".\.venv\Scripts\python.exe -m tools.report_nnue_showdown", "```", "",
        "Resume validates all frozen identities, skips completed games and continues saved in-progress moves. "
        "The amended entry point starts no additional games after G108. Do not use the original unbounded runner, "
        "whose retained historical plan still includes the omitted controls. Fresh experiments require a new dedicated output directory. "
        "The sealed dataset, original checkpoints, optimized v2/v3 networks and classical StockBear remain intact.", ""]
    (REPO / "NNUE_SHOWDOWN_REPORT.md").write_text("\n".join(lines), encoding="utf-8", newline="\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--allow-partial", action="store_true")
    args = parser.parse_args()
    result = analyze(args.root.resolve(), not args.allow_partial)
    print({"games": result["completed_games"], "audit": result["audit"]["passed"]})


if __name__ == "__main__":
    main()
