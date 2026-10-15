"""Immutable, interleaved native micro/search comparisons. No strength inference."""
import argparse
from contextlib import ExitStack
import json
from pathlib import Path
import statistics
import subprocess
import time

import chess
import chess.engine

from tools.audit_engine import metadata
from tools.benchmark_optimizations import POSITIONS as OLD

POSITIONS = {
    "opening": chess.STARTING_FEN,
    "quiet_middlegame": OLD["middlegame"],
    "tactical": OLD["tactical"],
    "king_attack": "6k1/5ppp/8/7Q/2B5/8/5PPP/6K1 w - - 0 1",
    "pawn_endgame": OLD["endgame"],
    "piece_endgame": "8/5pk1/6p1/3R4/8/5PK1/6P1/1r6 w - - 0 1",
    "imbalance": "r3k2r/ppp2ppp/2n5/8/3Q4/2N5/PPP2PPP/R3K3 w Qkq - 0 1",
    "castling_rights": "r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1",
    "promotion": "7k/4P3/8/8/8/8/5p2/K7 w - - 0 1",
    "en_passant": "r3k2r/8/8/3pP3/8/8/8/R3K2R w KQkq d6 0 1",
}


def summary(samples, key):
    values = [s[key] for s in samples]
    return {"median": statistics.median(values), "min": min(values), "max": max(values),
            "stdev": statistics.stdev(values) if len(values) > 1 else 0}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--repeats", type=int, default=3)
    p.add_argument("--nodes", type=int, default=100000)
    p.add_argument("--ms", type=int, default=200)
    p.add_argument("--micro-repeats", type=int, default=20000)
    p.add_argument("--micro-only", action="store_true")
    args = p.parse_args()
    if args.output.exists() or min(args.repeats, args.nodes, args.ms, args.micro_repeats) < 1:
        p.error("Choose a fresh output and positive budgets")
    configs = json.loads(args.config.read_text())
    data = {"method": "Serial rotated configuration order, single search thread, Hash=16 MB, fresh TT per go, warmup, no affinity lock; full search NPS is not raw evaluator throughput",
            "budgets": vars(args) | {"config": str(args.config), "output": str(args.output)},
            "configurations": {}, "positions": []}
    with ExitStack() as stack:
        engines = {}
        for label, config in configs.items():
            path = Path(config["engine"])
            engine = stack.enter_context(chess.engine.SimpleEngine.popen_uci(str(path.resolve()), timeout=60))
            engine.configure(config.get("options", {}) | {"Hash": 16})
            engines[label] = engine
            info = metadata(path)
            info["build"] = json.loads(path.with_suffix(".build.json").read_text())
            info["defaults"] = {n: o.default for n, o in engine.options.items()}
            info["overrides"] = config.get("options", {}) | {"Hash": 16}
            if config.get("micro"):
                info["micro"] = metadata(Path(config["micro"]))
                info["cpu"] = json.loads(subprocess.check_output([config["micro"], "--cpu"], text=True))
            data["configurations"][label] = info
            engine.play(chess.Board(), chess.engine.Limit(time=.05))
        labels = list(configs)
        for category, fen in POSITIONS.items():
            board = chess.Board(fen)
            assert board.is_valid(), (category, board.status())
            row = {"category": category, "fen": fen, "samples": {label: {"micro": [], "nodes": [], "time": []} for label in labels}}
            for repeat in range(args.repeats):
                order = labels[repeat % len(labels):] + labels[:repeat % len(labels)]
                for label in order:
                    config, engine = configs[label], engines[label]
                    samples = row["samples"][label]
                    if config.get("micro"):
                        samples["micro"].append(json.loads(subprocess.check_output(
                            [config["micro"], fen, str(args.micro_repeats)], text=True)))
                    if args.micro_only:
                        continue
                    for mode, limit in (("nodes", chess.engine.Limit(nodes=args.nodes)),
                                        ("time", chess.engine.Limit(time=args.ms / 1000))):
                        start = time.perf_counter()
                        info = engine.play(board, limit, info=chess.engine.INFO_ALL)
                        assert info.move in board.legal_moves
                        replay = board.copy()
                        for move in info.info.get("pv", []):
                            assert move in replay.legal_moves
                            replay.push(move)
                        result = info.info
                        samples[mode].append({"wall_seconds": time.perf_counter() - start,
                            "depth": result["depth"], "nodes": result["nodes"], "nps": result["nps"],
                            "seconds": result["time"], "move": info.move.uci(),
                            "score_white": str(result["score"].white())})
            row["summary"] = {label: {mode: {key: summary(samples, key) for key in
                (("head_ns", "feature_ns", "copy_ns", "update_ns", "refresh_ns", "classical_ns") if mode == "micro" else ("nps", "depth", "nodes", "wall_seconds"))}
                for mode, samples in modes.items() if samples} for label, modes in row["samples"].items()}
            data["positions"].append(row)
            print(category + ": " + "; ".join(f"{label} {row['summary'][label].get('time', {}).get('nps', {}).get('median', 0):,.0f} NPS" for label in labels), flush=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, indent=2) + "\n")


if __name__ == "__main__":
    main()
