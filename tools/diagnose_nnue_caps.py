"""Inspect capped end states offline without extending or adjudicating games."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess

import chess

from tools.nnue_diagnosis import RELEASE, ROOT, STOCKFISH, metadata, open_engine, save
from tools.run_nnue_diagnosis_positions import reference_search


def main() -> None:
    output = ROOT / "capped-position-analysis.json"
    if output.exists():
        raise ValueError("Frozen cap analysis exists")
    plan = json.loads((ROOT / "match-plan.json").read_text(encoding="utf-8"))
    data = {"method": "All capped end positions, offline SF19 300k nodes, Threads1, Hash64, cleared hash. Games remain unfinished regardless of reference score. No continuation or extra games; the amended runtime schedule takes priority. Primary 240-searched-ply cap stays fixed uniformly, and censoring-aware all-ten-pair bounds replace unjustified point imputations. Any future cap change must be prospectively uniform and separately recorded.",
            "reference_metadata": metadata(STOCKFISH), "cohorts": [], "records": []}
    with open_engine(STOCKFISH) as engine:
        engine.configure({"Threads": 1, "Hash": 64, "SyzygyPath": "", "UCI_LimitStrength": False})
        for scheduled in plan["schedule"]:
            record = json.loads(Path(scheduled["output"]).read_text(encoding="utf-8"))
            capped = [g for g in record["games"] if g["candidate_outcome"] == "unfinished"]
            data["cohorts"].append({"ms": scheduled["movetime"], "capped": len(capped), "scheduled": scheduled["games"],
                                    "fraction": len(capped) / scheduled["games"]})
            for game in capped:
                board = chess.Board()
                for move in game["opening"] + [r["move"] for r in game["searches"]]:
                    board.push_uci(move)
                assert not board.is_game_over(claim_draw=True) and len(game["searches"]) == 240
                static = {}
                for evaluator in ("nnue", "classical"):
                    flags = ["--nnue", "--kernel", "scalar"] if evaluator == "nnue" else []
                    static[evaluator] = json.loads(subprocess.check_output([str(RELEASE.resolve()), "--eval", *flags, board.fen()], text=True, timeout=10))
                data["records"].append({"ms": scheduled["movetime"], "game": game["game"], "pair": game["pair"],
                                        "fen": board.fen(), "nnue_color": game["candidate_color"],
                                        "halfmove_clock": board.halfmove_clock, "pieces": len(board.piece_map()),
                                        "last_searches": game["searches"][-2:], "static_white": static,
                                        "reference_root_side_to_move": reference_search(engine, board, board.turn, 300000)})
    save(output, data)


if __name__ == "__main__":
    main()
