"""Bounded outcome-blind samples from actual games, with preserved draw history."""
from __future__ import annotations

from collections import defaultdict
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path

import chess

from tools.analyze_nnue_diagnosis import bootstrap, candidate_quality, reference_rank
from tools.nnue_diagnosis import (BASE_OPTIONS, RELEASE, ROOT, SEED, STOCKFISH,
                                 capture, metadata, open_engine, save, sha)
from tools.run_nnue_diagnosis_positions import reference_search


def sample_positions() -> dict:
    plan = json.loads((ROOT / "match-plan.json").read_text(encoding="utf-8"))
    sources, selected, seen = {}, [], set()
    for scheduled in plan["schedule"]:
        path = Path(scheduled["output"])
        sources[str(path)] = sha(path)
        games = json.loads(path.read_text(encoding="utf-8"))["games"][:20]
        pools: dict[str, list[dict]] = defaultdict(list)
        for game in games:
            board = chess.Board()
            for move in game["opening"]:
                board.push_uci(move)
            for searched, search in enumerate(game["searches"]):
                pieces = len(board.piece_map())
                phase = "opening" if pieces >= 28 and board.ply() <= 24 else "endgame" if pieces <= 12 else "middlegame"
                if searched >= 4 and len(list(board.legal_moves)) >= 2 and not board.is_game_over(claim_draw=True):
                    key = f"{SEED}|{scheduled['movetime']}|{phase}|{game['game']}|{board.ply()}|{board.fen()}"
                    pools[phase].append({"fen": board.fen(), "moves": [m.uci() for m in board.move_stack],
                                         "game": game["game"], "pair": game["pair"], "ply": board.ply(),
                                         "selection_key": hashlib.sha256(key.encode()).hexdigest()})
                board.push_uci(search["move"])
        for phase in ("opening", "middlegame", "endgame"):
            pool = sorted(pools[phase], key=lambda r: r["selection_key"])
            row = next(r for r in pool if " ".join(r["fen"].split()[:4]) not in seen)
            seen.add(" ".join(row["fen"].split()[:4]))
            selected.append(row | {"id": f"game_{scheduled['movetime']}ms_{phase}", "category": phase,
                                   "source_ms": scheduled["movetime"], "eligible_pool_positions": len(pool)})
    return {"method": "One position per phase/control from first ten opening pairs (12 total), minimum SHA256(seed|control|phase|game|ply|fen), at least four searched plies, at least two legal moves; no scores, results or evaluator decisions used in selection. Opening >=28 pieces and <=24 total plies; endgame <=12 pieces; otherwise middle. Distinct piece/state positions; all pre-root move history retained. Supplementary to the predeclared 24-FEN suite; not an independent strength estimate.",
            "seed": SEED, "source_sha256": sources, "positions": selected}


def main() -> None:
    path = ROOT / "tournament-position-quality.json"
    if path.exists():
        raise ValueError("Frozen game-position analysis exists")
    sample = sample_positions()
    sample_path = ROOT / "tournament-position-sample.json"
    if sample_path.exists():
        assert json.loads(sample_path.read_text(encoding="utf-8")) == sample
    else:
        save(sample_path, sample)
    data = {"sample_sha256": sha(sample_path), "metadata": metadata(RELEASE),
            "reference_metadata": metadata(STOCKFISH), "records": [],
            "limits": {"stockbear_nodes": [100000, 400000], "stockfish_nodes_per_root_or_child": 300000,
                       "reference_options": {"Threads": 1, "Hash": 64, "SyzygyPath": "", "UCI_LimitStrength": False}}}
    progress = path.with_suffix(".progress.json")
    if progress.exists():
        data = json.loads(progress.read_text(encoding="utf-8"))
        assert data["sample_sha256"] == sha(sample_path)
        assert data["metadata"]["sha256"] == sha(RELEASE) and data["reference_metadata"]["sha256"] == sha(STOCKFISH)
    done = {r["position"] for r in data["records"]}
    with ExitStack() as stack:
        engines = {e: stack.enter_context(open_engine(RELEASE)) for e in ("nnue", "classical")}
        reference = stack.enter_context(open_engine(STOCKFISH))
        reference.configure({"Threads": 1, "Hash": 64, "SyzygyPath": "", "UCI_LimitStrength": False})
        for evaluator, engine in engines.items():
            engine.configure(BASE_OPTIONS | {"Evaluator": evaluator})
        for index, row in enumerate(sample["positions"]):
            if row["id"] in done:
                continue
            board = chess.Board()
            for move in row["moves"]:
                board.push_uci(move)
            root = reference_search(reference, board, board.turn, 300000)
            results = []
            for budget in (100000, 400000):
                for evaluator in (("nnue", "classical") if index % 2 else ("classical", "nnue")):
                    result = capture(engines[evaluator], row, "nodes", budget)
                    results.append(result | {"evaluator": evaluator})
            candidates = {}
            for move in sorted({r["move"] for r in results} | {root["move"]}):
                child = board.copy()
                child.push_uci(move)
                candidates[move] = reference_search(reference, child, board.turn, 300000)
            item = {"position": row["id"], "category": row["category"], "root": root, "candidates": candidates,
                    "searches": results, "paired_comparisons": []}
            for budget in (100000, 400000):
                both = {r["evaluator"]: r for r in results if r["budget"] == budget}
                quality = {e: candidate_quality(item, r["move"]) for e, r in both.items()}
                ns, cs = (candidates[both[e]["move"]] for e in ("nnue", "classical"))
                ncp, ccp = ns["score_root"]["cp"], cs["score_root"]["cp"]
                item["paired_comparisons"].append({"budget": budget, "nnue_move": both["nnue"]["move"],
                    "classical_move": both["classical"]["move"], "quality": quality,
                    "direct_classical_minus_nnue_child_cp": ccp - ncp if ccp is not None and ncp is not None else None,
                    "reference_preference_nnue": (reference_rank(ns) > reference_rank(cs)) - (reference_rank(ns) < reference_rank(cs))})
            data["records"].append(item)
            save(path.with_suffix(".progress.json"), data)
            print("Tournament sample", row["id"], len(candidates), "candidate moves", flush=True)
    data["summary"] = []
    for budget in (100000, 400000):
        comparisons = [c for r in data["records"] for c in r["paired_comparisons"] if c["budget"] == budget]
        values = [r["direct_classical_minus_nnue_child_cp"] for r in comparisons if r["direct_classical_minus_nnue_child_cp"] is not None]
        data["summary"].append({"nodes": budget, "positions": 12, "cp_comparable": len(values),
            "mean_direct_classical_minus_nnue_child_cp": sum(values) / len(values) if values else None,
            "paired_position_bootstrap_95": bootstrap(values),
            "reference_prefers_nnue": sum(r["reference_preference_nnue"] > 0 for r in comparisons),
            "reference_prefers_classical": sum(r["reference_preference_nnue"] < 0 for r in comparisons),
            "same_move": sum(r["nnue_move"] == r["classical_move"] for r in comparisons)})
    data["limitations"] = "Twelve selected game positions; phase stratification and shared games induce dependence. Conditional illustrative bootstrap, no population or Elo inference. Fixed node/child-reference budgets and complete draw histories do not eliminate search-policy differences."
    save(path, data)
    path.with_suffix(".progress.json").unlink(missing_ok=True)


if __name__ == "__main__":
    main()
