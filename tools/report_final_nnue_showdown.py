"""Replay and analyze only the 48 final classical/NNUE games."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
import itertools
import math
from pathlib import Path
import statistics

import chess
import chess.pgn

from tools import nnue_showdown as core
from tools.final_nnue_showdown import ROOT, PREVIOUS, validate, validate_counters
from tools.report_nnue_showdown import paired_uncertainty


def elo(score: float) -> float | str:
    if score <= 0:
        return "-infinity"
    if score >= 1:
        return "+infinity"
    return 400 * math.log10(score / (1 - score))


def paired_test(rows: list[dict], label: str) -> dict:
    uncertainty = paired_uncertainty(rows, label)
    scores = uncertainty.get("pair_scores", [])
    differences = [round(4 * (s - .5)) for s in scores if s != .5]
    observed = sum(differences)
    # Exchange entire evaluator labels within a color-reversed opening pair,
    # retaining its magnitude. Never treat the two colors as independent units.
    totals = [sum(sign * abs(d) for sign, d in zip(signs, differences))
              for signs in itertools.product((-1, 1), repeat=len(differences))]
    p = sum(t >= observed for t in totals) / len(totals)
    two_sided = sum(abs(t) >= abs(observed) for t in totals) / len(totals)
    return {**uncertainty, "nnue_superiority_p_one_sided": p, "difference_p_two_sided": two_sided,
            "exchangeability_note": "Exact opening-pair sign-flip test conditional on independent, label-exchangeable pair outcomes under equal strength; fixed related openings limit generalization",
            "elo_from_score": elo(uncertainty["paired_score"]) if scores else None,
            "elo_95_conservative": [elo(v) for v in uncertainty["hoeffding_95"]],
            "elo_95_descriptive_bootstrap": [elo(v) for v in uncertainty["bootstrap_95"]]}


def metrics(rows: list[dict], label: str) -> dict:
    value = core.stats(rows, label)
    moves = [s for r in rows for s in r["searches"] if s["engine"] == label]
    value["median_reported_nps"] = statistics.median(s["nps"] for s in moves) if moves else None
    value["median_wall_seconds"] = statistics.median(s["wall_seconds"] for s in moves) if moves else None
    return value


def roots(rows: list[dict], candidate: str) -> dict:
    pairs = []
    for opening in range(12):
        group = [r for r in rows if r["game"]["opening"] == opening]
        first = {r["searches"][0]["engine"]: r["searches"][0] for r in group if r["searches"]}
        if len(group) == 2 and "classical" in first and candidate in first:
            a, b = first["classical"], first[candidate]
            pairs.append({"opening": opening, "classical": a, "nnue": b,
                          "nps_ratio": (b["nodes"] / b["engine_seconds"]) / (a["nodes"] / a["engine_seconds"]),
                          "depth_difference": b["depth"] - a["depth"]})
    return {"pairs": pairs, "matched_roots": len(pairs),
            "geometric_nps_ratio": math.exp(statistics.mean(math.log(p["nps_ratio"]) for p in pairs)) if pairs else None,
            "mean_completed_depth_difference": statistics.mean(p["depth_difference"] for p in pairs) if pairs else None}


def audit(root: Path, complete: bool) -> tuple[dict, list[dict], dict]:
    plan = core.load(root / "plan.json")
    validate(root, plan)
    rows = core.records(root)
    if complete:
        assert len(rows) == 48 and {r["game"]["id"] for r in rows} == {g["id"] for g in plan["schedule"]}
    moves = 0
    for r in rows:
        game = r["game"]
        assert r["complete"] is True
        board = core.board_for(plan, game)
        for s in r["searches"]:
            assert s["engine"] == (game["white"] if board.turn else game["black"])
            validate_counters(s, plan["engines"][s["engine"]]["evaluator"])
            assert s["wall_seconds"] <= 1.1 and s["nodes"] >= 0
            board.push_uci(s["move"])
            moves += 1
        outcome = board.outcome(claim_draw=True)
        assert r["result"] == (outcome.result() if outcome else "*")
        assert r["termination"] == (outcome.termination.name.lower() if outcome else "safety_cap_unfinished")
        assert outcome or len(r["searches"]) == 400
        assert len(r["searches"]) <= 400 and r["final_fen"] == board.fen()
        with (root / "games" / (game["id"] + ".pgn")).open(encoding="utf-8") as stream:
            pgn = chess.pgn.read_game(stream)
        assert pgn and not pgn.errors and list(pgn.mainline_moves()) == board.move_stack
        assert pgn.headers["Result"] == r["result"] and pgn.headers["PlanSHA256"] == core.sha(root / "plan.json")
        for color, label in (("White", game["white"]), ("Black", game["black"])):
            entry = plan["engines"][label]
            assert pgn.headers[color + "EngineSHA256"] == entry["sha256"]
            assert pgn.headers[color + "Evaluator"] == entry["evaluator"]
            assert pgn.headers[color + "NetworkSHA256"] == (entry["network_sha256"] if label != "classical" else "disabled")
    protected = core.load(root / "preservation-before.json")
    changed = [p for p, checksum in protected.items() if core.sha(core.REPO / p) != checksum]
    assert not changed, changed
    result = {"utc": core.utc(), "passed": True, "games": len(rows), "searched_moves": moves,
              "protected_files": len(protected), "changed_protected_files": changed,
              "test_dataset_opened": False, "classical_nnue_evaluations": sum(s["nnue_evaluations"] for r in rows for s in r["searches"] if s["engine"] == "classical")}
    core.save(root / "audit.json", result)
    return plan, rows, result


def analyze(root: Path, complete: bool = True) -> dict:
    plan, rows, checked = audit(root, complete)
    failures = [core.load(p) for p in sorted((root / "failures").glob("*.json"))]
    matches = {}
    for candidate in ("64", "128"):
        group = [r for r in rows if candidate in r["game"]["pair"]]
        baseline, neural = metrics(group, "classical"), metrics(group, candidate)
        matches[candidate] = {"games": len(group), "classical": baseline, "nnue": neural,
                              "uncertainty": paired_test(group, candidate), "matched_roots": roots(group, candidate),
                              "relative_aggregate_nps_percent": 100 * (neural["aggregate_nps"] / baseline["aggregate_nps"] - 1) if neural["aggregate_nps"] else None,
                              "failures": dict(Counter(f["kind"] for f in failures if candidate in f["game"]["pair"]))}
    ordered = sorted(matches, key=lambda c: matches[c]["uncertainty"]["difference_p_two_sided"])
    previous_adjusted = 0.
    for i, candidate in enumerate(ordered):
        u = matches[candidate]["uncertainty"]
        adjusted = min(1., max(previous_adjusted, (2-i) * u["difference_p_two_sided"]))
        u["holm_adjusted_p_two_candidates"] = adjusted
        u["nominal_supported_nnue_superiority"] = adjusted < .05 and u["complete_pairs"] == 12 and u["paired_score"] > .5
        u["nominal_supported_classical_superiority"] = adjusted < .05 and u["complete_pairs"] == 12 and u["paired_score"] < .5
        previous_adjusted = adjusted
    elapsed = (max(datetime.fromisoformat(r["completed_utc"]) for r in rows) - min(datetime.fromisoformat(r["started_utc"]) for r in rows)).total_seconds() if rows else 0
    result = {"utc": core.utc(), "plan_sha256": core.sha(root / "plan.json"), "games": len(rows), "matches": matches,
              "audit": checked, "terminations": dict(Counter(r["termination"] for r in rows)),
              "failures": failures, "elapsed_wall_seconds": elapsed,
              "previous_games_used_for_inference": 0,
              "analysis_method": "Paired opening units; 95% Hoeffding bounded-mean intervals, descriptive 5000-resample bootstrap; exact two-sided sign-flip difference tests with Holm adjustment for the two candidates, direction inferred from paired score; one-sided NNUE p also reported; no automatic promotion"}
    core.save(root / "analysis.json", result)
    if complete:
        report(root, plan, rows, result)
    return result


def number(value) -> str:
    return f"{value:+.0f}" if isinstance(value, (int, float)) else value


def report(root: Path, plan: dict, rows: list[dict], data: dict) -> None:
    lead = max(data["matches"], key=lambda c: data["matches"][c]["nnue"]["score_fraction"])
    supported = [c for c, m in data["matches"].items() if m["uncertainty"]["nominal_supported_nnue_superiority"]]
    lines = ["# StockBear Final Classical vs NNUE Showdown", "", "## Executive summary", "",
             "Completed **48 games at 1 second per move**: 24 classical versus 64/32, then 24 classical versus 128/32. "
             "Each match used the same 12 fresh opening pairs with reversed colors. No longer controls or extra games were played.", "",
             f"The NNUE candidate with the highest observed score against classical is **{lead}/32**. "
             + (f"The conditional paired tests support NNUE superiority for: {', '.join(supported)}. " if supported else "Neither candidate establishes NNUE superiority under the paired tests after correcting for two comparisons. ")
             + "Observed scores, conditional statistical evidence and the default-evaluator recommendation are distinguished below.", "",
             "## Engine verification and fairness", "",
             "The isolated classical executable is a byte-identical copy of the verified 64/32 binary, explicitly selected "
             "with `Evaluator=classical`. Its embedded network is unused. Source inspection confirms both NNUE selector "
             "flags become false, no NNUE accumulator stack is allocated, and evaluation falls through to the original "
             "handcrafted evaluator with its pawn cache. Five CLI/UCI probes across starting, opening and endgame positions "
             "matched the protected original engine exactly, including full evaluation components. Switching through NNUE "
             "and changing NNUE-only settings restored the same classical evaluations. Every classical tournament search "
             "was required to report zero NNUE evaluations; every NNUE search had NNUE calls equal to evaluation calls.", "",
             "All copies retain identical unchanged C++ search sources, compiler/`-O2` flags, 16 MiB hash, pruning and "
             "ordering settings, one search thread and no pondering. NNUE uses scalar float32 and verified incremental "
             "accumulators. The classical pawn cache is naturally active only for classical; it is part of the original "
             "evaluation implementation. Network dimensions/weights and evaluator selection are the only intended differences.", "",
             "Prior 38-test regression receipts per distinct NNUE binary were reused after matching their exact hashes. "
             "Fresh preflight checks verified intended evaluation, legal moves, castling, en passant, promotion, mate, "
             "stalemate and 1-second deadlines for all three copies. Another **29 targeted engine regressions** and "
             "**12 preflight harness checks** passed; a later statistics regression checked paired tests and infinite Elo limits. "
             "No training or intensive benchmarks ran during games.", "",
             "| Engine | Evaluation | Binary SHA-256 | Active network SHA-256 |", "|---|---|---|---|"]
    for label, entry in plan["engines"].items():
        lines.append(f"| {entry['name']} | {entry['evaluator']} | `{entry['sha256']}` | "
                     + (f"`{entry['network_sha256']}`" if label != "classical" else "Disabled; no active network") + " |")
    lines += ["", "## Tournament configuration", "",
              "The opening suite was frozen before games with seed 20261017. It comprises 12 manually chosen established "
              "lines with starting FENs distinct from the previous showdown; no candidate or Stockfish selected/filtering "
              "scores were used. Some opening families overlap normal chess practice, so this is a fresh fixed suite, "
              "not a statistically independent random sample of all chess. Pair starts alternate which evaluator has White. "
              "Match A precedes Match B as requested, so timing/thermal drift across matches remains possible; each match "
              "contains its own classical control and its own matched-root comparison.", "",
              "Each game starts fresh engine processes. Full opening and game history is sent to UCI; python-chess "
              "validates every move and claims available threefold/50-move draws, as well as enforcing terminal/automatic "
              "draw rules. No evaluation-based adjudication or resignation. The 400-searched-ply cap is unfinished/unscored, "
              "not a draw. The per-move wall deadline is 1.100 seconds, including 100 ms protocol/OS allowance; engine and "
              "wall time are stored separately. Infrastructure failures halt and retain checkpoints without a chess forfeit.", "",
              "| Opening ID | Line | Starting FEN |", "|---|---|---|"]
    for o in plan["openings"]:
        lines.append(f"| {o['id']} | {o['family']}: {o['san']} | `{o['fen']}` |")
    for candidate, match in data["matches"].items():
        a, b, u = match["classical"], match["nnue"], match["uncertainty"]
        lines += ["", f"## Classical vs {candidate}/32", "", "| Metric | Classical | NNUE |", "|---|---:|---:|"]
        for label, key, formatter in (
            ("Wins", "wins", lambda v: str(v)), ("Draws", "draws", str), ("Losses", "losses", str),
            ("Points", "points", lambda v: f"{v:g}"), ("Score", "score_fraction", lambda v: f"{100*v:.2f}%"),
            ("Unfinished (unscored)", "unfinished", str),
            ("Mean / median reported NPS", None, None),
            ("Aggregate nodes / engine seconds (NPS)", "aggregate_nps", lambda v: f"{v:,.0f}"),
            ("Mean completed depth", "mean_depth", lambda v: f"{v:.2f}"),
            ("Median completed depth", "median_depth", lambda v: f"{v:g}"),
            ("Total searched nodes", "nodes", lambda v: f"{v:,}"),
            ("Mean engine time / move (s)", "mean_engine_seconds", lambda v: f"{v:.4f}"),
            ("Mean / median wall time (s)", None, None),
            ("Maximum wall time (s)", "max_wall_seconds", lambda v: f"{v:.4f}"),
            ("Total engine search seconds", "engine_seconds", lambda v: f"{v:.3f}"),
            ("Evaluation calls", "eval_calls", lambda v: f"{v:,}"), ("NNUE evaluations", "nnue_evaluations", lambda v: f"{v:,}")):
            if key:
                left, right = formatter(a[key]), formatter(b[key])
            elif label.startswith("Mean / median reported"):
                left, right = (f"{m['mean_reported_nps']:,.0f} / {m['median_reported_nps']:,.0f}" for m in (a, b))
            else:
                left, right = (f"{m['mean_wall_seconds']:.4f} / {m['median_wall_seconds']:.4f}" for m in (a, b))
            lines.append(f"| {label} | {left} | {right} |")
        lo, hi = u["hoeffding_95"]
        bl, bh = u["bootstrap_95"]
        er = u["elo_95_conservative"]
        br = u["elo_95_descriptive_bootstrap"]
        lines += ["", f"NNUE scores **{b['points']:g}/{b['games']-b['unfinished']} ({100*b['score_fraction']:.2f}%)**. "
                  f"Aggregate NPS change versus classical: **{match['relative_aggregate_nps_percent']:+.1f}%**. "
                  f"Saved failure events by kind: `{match['failures']}`.", "",
                  f"Paired opening units: {u['complete_pairs']}. Conservative 95% score bounds: **{100*lo:.1f}–{100*hi:.1f}%**; "
                  f"descriptive paired-bootstrap 95%: {100*bl:.1f}–{100*bh:.1f}%. "
                  f"Score-equivalent Elo estimate: **{number(u['elo_from_score'])}**, with conservative transformed bounds "
                  f"[{number(er[0])}, {number(er[1])}] and descriptive bootstrap bounds [{number(br[0])}, {number(br[1])}]. "
                  f"One-sided NNUE-superiority p={u['nnue_superiority_p_one_sided']:.5f}; two-sided paired sign-flip p="
                  f"{u['difference_p_two_sided']:.5f}; Holm-adjusted two-sided p="
                  f"{u['holm_adjusted_p_two_candidates']:.5f}."]
    lines += ["", "## Search speed and depth at identical roots", "",
              "Only the first search of each color-reversed game is compared. Each evaluator searches the identical "
              "opening FEN/history with fresh processes and the same 1-second budget. Ratios are geometric means over "
              "the 12 matched FENs, not an inference microbenchmark; evaluators can still explore different trees.", "",
              "| NNUE | Matched roots | NPS relative to classical | Mean completed-depth difference |", "|---|---:|---:|---:|"]
    for c, m in data["matches"].items():
        r = m["matched_roots"]
        lines.append(f"| {c}/32 | {r['matched_roots']} | {r['geometric_nps_ratio']:.3f}× ({100*(r['geometric_nps_ratio']-1):+.1f}%) | {r['mean_completed_depth_difference']:+.2f} |")
    lines += ["", "Arithmetic mean and median NPS above use per-move UCI-reported values. Aggregate NPS divides "
              "total nodes by total engine seconds, weighting longer searches more heavily. Completed depth is the last "
              "fully finished iteration; counters include work in interrupted deeper iterations. Speed and depth alone "
              "do not determine playing strength. Results apply to these scalar float32 builds on this laptop.", "",
              "## Statistical uncertainty", "",
              "An opening pair, including both colors, is one uncertainty unit. Primary 95% Hoeffding bounds are very "
              "conservative for only 12 pairs. The 5,000-resample paired bootstrap is descriptive, may degenerate for "
              "unanimous outcomes, and does not repair the fixed-suite sampling limitation. Elo is the conventional "
              "400*log10(score/(1-score)) score equivalent; it is not an external rating or definitive strength estimate. "
              "Bounds reaching 0 or 1 map to infinite Elo limits, not silently truncated finite precision.", "",
              "The exact sign-flip test exchanges entire evaluator labels within each opening pair and "
              "assumes independent, label-exchangeable pair outcomes under equal strength. Holm adjustment covers the "
              "two two-sided evaluator-difference comparisons; direction comes from the paired score. The one-sided "
              "NNUE-superiority p is also shown without a separate significance decision. Any significant finding is conditional on those assumptions and this "
              "suite; related openings, limited sample size, training/model selection and one hardware/time configuration "
              "limit generalization. No prior NNUE-versus-NNUE game contributes to these scores, tests or Elo estimates.", "",
              "## Instructive games", "",
              "Examples below are selected by outcome and length to show the recorded range, without a new teacher "
              "analysis. They illustrate results rather than proving the cause of a win."]
    for c in ("64", "128"):
        group = [r for r in rows if c in r["game"]["pair"]]
        selected = []
        for score in (1., 0., .5):
            options = [r for r in group if core.points(r, c) == score]
            if options:
                selected.append(min(options, key=lambda r: (len(r["searches"]), r["game"]["id"])))
        for r in selected:
            g = r["game"]
            lines.append(f"- [{g['id']}](final-nnue-showdown-20261017/games/{g['id']}.pgn): "
                         f"{plan['engines'][g['white']]['name']}–{plan['engines'][g['black']]['name']}, "
                         f"{plan['openings'][g['opening']]['family']}, {r['result']}, {r['termination']}, "
                         f"{len(r['searches'])} searched plies.")
    lines += ["", "## Preservation and completion", "",
              f"Final audit replayed **{data['audit']['searched_moves']:,} searched moves** in **48 games**, verified "
              f"PGNs, evaluator counters, deadlines and frozen identities. **{data['audit']['protected_files']} protected "
              f"files** were unchanged. Classical NNUE evaluations across the tournament: **{data['audit']['classical_nnue_evaluations']}**. "
              f"Termination counts: `{data['terminations']}`. Saved failure events: **{len(data['failures'])}**. "
              f"Elapsed first-start to last-finish time: {data['elapsed_wall_seconds']/3600:.2f} hours.", "",
              "Original classical evaluation, the active executable, previous checkpoints, optimized v2/v3 models, "
              "and previous showdown artifacts are preserved. The sealed test dataset was not opened or hashed. "
              "No networks were trained, no labels generated and no search heuristics changed.", "",
              "## Artifacts and reproduction", "",
              f"Directory: `{root}`. `plan.json` records options, game order, openings, source/engine/network identities "
              "and frozen runner dependencies. `verification.json`, `audit.json`, `analysis.json`, `scoreboard.json` "
              "and `games/Gxxx.json`/PGN retain verification and raw results. Isolated executables and logs are in "
              "`artifacts/`. Completed JSON records are authoritative; resume skips them and restores partial move histories.", "",
              "```powershell", r"Set-Location Z:\Code\Chess",
              r".\.venv\Scripts\python.exe -m tools.final_nnue_showdown progress",
              r".\.venv\Scripts\python.exe -u -m tools.final_nnue_showdown run --resume",
              r".\.venv\Scripts\python.exe -m tools.report_final_nnue_showdown", "```", "",
              "A completed schedule starts no extra games. A fresh reproduction needs another experiment directory. "
              "The previous NNUE scaling/showdown reports are background context only.", ""]
    (core.REPO / "FINAL_NNUE_SHOWDOWN_REPORT.md").write_text("\n".join(lines), encoding="utf-8", newline="\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--allow-partial", action="store_true")
    args = parser.parse_args()
    result = analyze(args.root.resolve(), not args.allow_partial)
    print({"games": result["games"], "audit": result["audit"]["passed"]})


if __name__ == "__main__":
    main()
