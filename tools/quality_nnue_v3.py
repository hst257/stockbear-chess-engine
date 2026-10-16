"""Outcome-blind equal-node diagnostic with separate fixed-budget reference searches."""
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import random
import sqlite3
import statistics

import chess
import chess.engine

from tools.nnue_diagnosis import BASE_OPTIONS, STOCKFISH, capture, metadata, open_engine, positions
from tools.benchmark_nnue_v3 import BUILDS, MODEL, ROOT
from tools.match_optimizations import write_record


def main() -> None:
    path = ROOT / "quality.json"
    plan = ROOT / "quality-plan.json"
    if plan.exists():
        suite = json.loads(plan.read_text())["positions"]
    else:
        suite = [r | {"source": "Prior frozen hand-selected suite"} for r in positions()]
        rng = random.Random(20261016)
        board, generated = chess.Board(), []
        for n in range(2000):
            if board.is_game_over() or board.ply() > 160:
                board = chess.Board()
            board.push(rng.choice(list(board.legal_moves)))
            if n % 37 == 0 and not board.is_game_over():
                generated.append(board.copy(stack=False))
        seen = {r["fen"] for r in suite}
        pool = Path("StockBear_NNUE_training/data/v2/pool.sqlite").resolve()
        with sqlite3.connect(f"file:{pool.as_posix()}?mode=ro", uri=True) as db:
            for board in generated:
                fen = " ".join(board.fen().split()[:4]) + " 0 1"
                key = hashlib.sha256(fen.encode()).hexdigest()
                if fen in seen or db.execute("SELECT 1 FROM positions WHERE id=?", (key,)).fetchone():
                    continue
                seen.add(fen)
                suite.append({"id": f"fresh_{len(suite)-24:02d}", "fen": fen, "category": "random_legal_walk",
                              "source": "New seeded legal walk, no outcome/evaluation filtering, absent from source pool"})
                if len(suite) == 48:
                    break
        assert len(suite) == 48
        write_record(plan, json.dumps({"positions": suite, "candidate_nodes": 100000, "reference_nodes": 65536,
            "method": "24 frozen diagnostic FENs plus 24 new outcome-blind legal walk FENs. Fresh root and child reference searches, no tablebases. Negative raw deltas retained; CPL clipped at zero. Mate results separate. Stockfish also supplied training labels, so this is not independent playing strength."}, indent=2) + "\n")
    data = json.loads(path.read_text()) if path.exists() else {
        "builds": {k: metadata(v) for k,v in BUILDS.items()}, "teacher_reference": metadata(STOCKFISH), "records": []}
    done = {r["position"] for r in data["records"]}
    with ExitStack() as stack:
        engines = {k: stack.enter_context(open_engine(v)) for k,v in BUILDS.items()}
        teacher = stack.enter_context(open_engine(STOCKFISH))
        teacher.configure({"Threads": 1, "Hash": 64})
        for label, engine in engines.items():
            opts = BASE_OPTIONS | {"Evaluator": "classical" if label == "classical" else "nnue" if label == "v2" else "nnue_v3"}
            if label == "v3": opts = {"NNUEV3File": str(MODEL.resolve())} | opts
            engine.configure(opts)
        for row in suite:
            if row["id"] in done: continue
            board = chess.Board(row["fen"])
            reference = teacher.analyse(board, chess.engine.Limit(nodes=65536), game=object())
            root_cp = reference["score"].pov(board.turn).score()
            root_move = reference["pv"][0].uci()
            candidates = {k: capture(v, row, "nodes", 100000) for k,v in engines.items()}
            children = {}
            for move in {r["move"] for r in candidates.values()}:
                child = board.copy()
                child.push_uci(move)
                info = teacher.analyse(child, chess.engine.Limit(nodes=65536), game=object())
                score = info["score"].pov(board.turn)
                children[move] = {"cp": score.score(), "mate": score.mate(), "nodes": info.get("nodes", 0),
                                  "depth": info.get("depth", 0), "terminal": child.is_game_over(claim_draw=True)}
            data["records"].append({"position": row["id"], "category": row["category"], "fen": row["fen"],
                "reference": {"move": root_move, "cp": root_cp, "mate": reference["score"].pov(board.turn).mate(), "nodes": reference["nodes"]},
                "candidates": candidates, "children": children})
            write_record(path, json.dumps(data, indent=2) + "\n")
            print("Quality", row["id"], flush=True)
    summary = {}
    for cohort in ("all", "frozen", "fresh"):
        records = [r for r in data["records"] if cohort == "all" or r["position"].startswith("fresh_") == (cohort == "fresh")]
        summary[cohort] = {}
        for label in engines:
            deltas, agreement, mates = [], 0, 0
            for row in records:
                move = row["candidates"][label]["move"]
                agreement += move == row["reference"]["move"]
                child = row["children"][move]
                if row["reference"]["cp"] is not None and child["cp"] is not None:
                    deltas.append(row["reference"]["cp"] - child["cp"])
                else: mates += 1
            summary[cohort][label] = {"positions": len(records), "best_move_agreement": agreement,
                "finite_cp_cases": len(deltas), "mean_cpl": statistics.mean(max(0, x) for x in deltas),
                "median_cpl": statistics.median(max(0, x) for x in deltas), "negative_raw_deltas": sum(x<0 for x in deltas),
                "reference_cpl_ge_150_heuristic": sum(x>=150 for x in deltas), "mate_cases_separate": mates}
    write_record(ROOT / "quality-summary.json", json.dumps(summary, indent=2) + "\n")


if __name__ == "__main__":
    main()
