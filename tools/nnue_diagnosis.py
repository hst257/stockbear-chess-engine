"""Shared frozen inputs and serial search capture for the diagnostic study."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import time

import chess
import chess.engine

from tools.benchmark_nnue_v2 import POSITIONS as OLD
from tools.match_optimizations import write_record

ROOT = Path(os.environ.get("STOCKBEAR_DIAGNOSIS_ROOT", "docs/nnue-v2-diagnosis"))
ARTIFACTS = Path(os.environ.get("STOCKBEAR_DIAGNOSIS_ARTIFACTS", "artifacts/nnue-v2-diagnosis"))
RELEASE = Path(os.environ.get("STOCKBEAR_DIAGNOSIS_ENGINE", "artifacts/nnue-v2/final-compact/engine.exe"))
DIAGNOSTIC = ARTIFACTS / "counters/engine.exe"
PROFILE = ARTIFACTS / "profile/engine.exe"
STOCKFISH = Path("StockBear_NNUE_training/stockfish-windows-x86-64-universal/stockfish/stockfish-windows-x86-64-universal.exe")
SEED = 20261017
ABLATIONS = {"production": {}, "no_lmr": {"UseLMR": False},
             "no_null": {"UseNullMovePruning": False}, "no_futility": {"UseFutility": False},
             "no_reverse_futility": {"UseReverseFutility": False},
             "no_aspiration": {"UseAspirationWindows": False}}
BASE_OPTIONS = {"Hash": 16, "NNUEKernel": "scalar", "NNUEIncremental": True}
FENS = (
    ("opening", "start", chess.STARTING_FEN),
    ("opening", "queen_gambit", "rnbqkb1r/ppp2ppp/4pn2/3p4/2PP4/2N5/PP2PPPP/R1BQKBNR w KQkq - 2 4"),
    ("quiet_middlegame", "old_middle", OLD["quiet_middlegame"]),
    ("quiet_middlegame", "italian_structure", "r1bq1rk1/pp2bppp/2nppn2/2p5/2B1P3/2NP1N2/PPP2PPP/R1BQ1RK1 w - - 4 8"),
    ("tactical", "kiwipete", OLD["tactical"]),
    ("tactical", "pins", "r4rk1/1pp1qppp/p1np1n2/2b1p1B1/2B1P1b1/P1NP1N2/1PP1QPPP/R4RK1 w - - 0 10"),
    ("king_attack", "attack_complex", "r3r1k1/ppp2ppp/2n2n2/2bq4/3P4/2PBBN2/PP3PPP/R2Q1RK1 w - - 0 12"),
    ("king_attack", "mate_net", OLD["king_attack"]),
    ("material_imbalance", "queen_rooks", OLD["imbalance"]),
    ("material_imbalance", "rook_minors", "2r3k1/pp3ppp/8/8/2B5/2N5/PP3PPP/6K1 b - - 0 1"),
    ("pawn_endgame", "old_pawns", OLD["pawn_endgame"]),
    ("pawn_endgame", "opposed_pawns", "8/5pk1/6p1/3p4/3P4/5PK1/6P1/8 w - - 0 1"),
    ("piece_endgame", "rooks", OLD["piece_endgame"]),
    ("piece_endgame", "rook_bishop", "8/2r2pk1/6p1/3B4/8/5PK1/6P1/1R6 w - - 0 1"),
    ("passed_pawns", "outside_passer", "8/5pk1/6p1/2P5/8/5PK1/6P1/8 w - - 0 1"),
    ("passed_pawns", "rook_pawn", "8/1p4k1/8/P7/8/8/6K1/8 b - - 0 1"),
    ("promotion", "promotion_race", OLD["promotion"]),
    ("promotion", "underpromotion_perft", "rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 8"),
    ("zugzwang", "white_blocked", "8/3k4/3P4/3K4/8/8/8/8 w - - 0 1"),
    ("zugzwang", "black_blocked", "8/8/8/3k4/3p4/3K4/8/8 b - - 0 1"),
    ("defense", "defend_mate_net", "6k1/5ppp/8/7Q/2B5/8/5PPP/6K1 b - - 0 1"),
    ("defense", "defend_complex", "r3r1k1/ppp2ppp/2n2n2/2bq4/3P4/2PBBN2/PP3PPP/R2Q1RK1 b - - 0 12"),
    ("long_term_planning", "carlsbad", "r1bq1rk1/ppp2ppp/2n1pn2/3p4/3P4/2PBPN2/PP3PPP/RNBQ1RK1 w - - 0 8"),
    ("long_term_planning", "locked_center", "r1bq1rk1/pp2bppp/2n1pn2/2ppP3/3P4/2PB1N2/PP3PPP/RNBQ1RK1 w - - 0 8"),
)


def save(path: Path, data: dict) -> None:
    write_record(path, json.dumps(data, indent=2, allow_nan=False) + "\n")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def metadata(path: Path) -> dict:
    sidecar = path.with_suffix(".build.json")
    return {"utc": datetime.now(timezone.utc).isoformat(), "executable": str(path.resolve()), "sha256": sha(path),
            "platform": platform.platform(), "processor": os.environ.get("PROCESSOR_IDENTIFIER", platform.processor()),
            "logical_cpus": os.cpu_count(), "python": platform.python_version(),
            "source_revision": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
            "build": json.loads(sidecar.read_text(encoding="utf-8")) if sidecar.exists() else None}


def positions() -> list[dict]:
    rows = [{"category": category, "id": name, "fen": fen} for category, name, fen in FENS]
    for row in rows:
        board = chess.Board(row["fen"])
        assert board.is_valid() and not board.is_game_over(claim_draw=True), row
        row["pieces"] = len(board.piece_map())
        row["nominal_phase"] = "endgame" if row["pieces"] <= 12 else "opening" if row["category"] == "opening" else "middlegame"
        row["short_forced_fixture"] = row["id"] in ("mate_net", "defend_mate_net")
    return rows


def open_engine(path: Path) -> chess.engine.SimpleEngine:
    flags = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    return chess.engine.SimpleEngine.popen_uci(str(path.resolve()), timeout=120, **flags)


def score_value(score: chess.engine.Score) -> dict:
    return {"cp": score.score(), "mate": score.mate()}


def capture(engine: chess.engine.SimpleEngine, row: dict, mode: str, budget: int) -> dict:
    """Capture final totals and each published complete iteration separately."""
    board = chess.Board(row["fen"])
    limit = {"time": chess.engine.Limit(time=budget / 1000), "nodes": chess.engine.Limit(nodes=budget),
             "depth": chess.engine.Limit(depth=budget)}[mode]
    iterations, counters, special = [], {}, {}
    started = time.perf_counter()
    with engine.analysis(board, limit, game=object(), info=chess.engine.INFO_ALL) as analysis:
        for info in analysis:
            message = info.get("string", "")
            if message.startswith(("diagnostics ", "profile ")):
                name, encoded = message.split(" ", 1)
                special[name] = json.loads(encoded)
            else:
                counters.update({k: int(v) for k, v in re.findall(r"\b([a-z_]+)\s+(\d+)\b", message)})
            # Completed reports include score/PV. Interrupted-total reports omit
            # score, retaining the previous completed decision in merged info.
            if "depth" in info and "score" in info:
                iterations.append({"depth": info["depth"], "nodes": info.get("nodes"), "seconds": info.get("time"),
                                   "score_white": score_value(info["score"].white()),
                                   "pv": [m.uci() for m in info.get("pv", [])], "counters": dict(counters)})
        result = analysis.wait()
        info = dict(analysis.info)
    wall = time.perf_counter() - started
    if mode == "time":
        assert wall < budget / 1000 + 5, (row["id"], "time watchdog", wall)
    assert result.move in board.legal_moves, (row["id"], result)
    replay = board.copy()
    for move in info.get("pv", []):
        assert move in replay.legal_moves
        replay.push(move)
    if mode == "depth":
        assert info["depth"] == budget, (row["id"], info)
    if mode == "nodes":
        assert info["nodes"] <= budget
    return {"position": row["id"], "mode": mode, "budget": budget, "depth": info.get("depth", 0),
            "seldepth": info.get("seldepth"), "nodes": info.get("nodes", 0), "nps": info.get("nps", 0),
            "seconds": info.get("time", 0), "wall_seconds": wall, "move": result.move.uci(),
            "score_white": score_value(info["score"].white()) if "score" in info else None,
            "pv": [m.uci() for m in info.get("pv", [])], "counters": counters,
            "iterations": iterations, **special}


def prepare_suite() -> dict:
    path = ROOT / "positions.json"
    expected = {"method": "Frozen before position experiments; two legal hand-selected fixtures per requested category. Bounded diagnostic examples, not a random strength sample or training data. Some categories overlap; two short mate fixtures are excluded from aggregate throughput.", "positions": positions(),
                "search_plan": {"time_ms": [50, 200, 1000], "nodes": [25000, 100000, 400000], "depth": [3, 4, 5], "repeats": 3},
                "ablation_plan": {"configurations": ABLATIONS, "time_ms": 200, "nodes": 100000, "repeats": 2},
                "reference_plan": {"engine": str(STOCKFISH), "threads": 1, "hash_mb": 64, "nodes": 300000,
                                   "method": "One independent root search and a fresh child search for every distinct candidate move, each with 300000 nodes. Both mapped to original root side-to-move. Root and child context differ by one ply; raw deltas retained, negative CPL clipped to zero and reported. Mates kept separate. No tablebases or assistance during matches."}}
    if path.exists():
        assert json.loads(path.read_text(encoding="utf-8")) == expected
    else:
        save(path, expected)
    return expected


if __name__ == "__main__":
    data = prepare_suite()
    print("Frozen", len(data["positions"]), "positions", sha(ROOT / "positions.json"))
