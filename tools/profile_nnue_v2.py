"""Collect exclusive instrumented timings, never compare instrumented NPS to release."""
import json
import argparse
from pathlib import Path
import chess
import chess.engine
from tools.audit_engine import metadata, measure
from tools.benchmark_nnue_v2 import POSITIONS


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("original", "final"), default="original")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    path = args.output or Path(f"docs/nnue-v2/profile-{args.stage}.json")
    if path.exists():
        raise ValueError("Frozen report exists")
    data = {"method": "Internal steady_clock exclusive scopes, three 300ms searches/category; instrumentation overhead included. No hardware cache/branch counters collected; WPR installed, WPA/VS profiler unavailable.", "models": {}}
    for model in ("compact", "small"):
        directory = f"profile-{model}" if args.stage == "original" else f"profile-final-{model}"
        binary = Path(f"artifacts/nnue-v2/{directory}/engine.exe")
        rows = []
        with chess.engine.SimpleEngine.popen_uci(str(binary.resolve())) as engine:
            engine.configure({"Evaluator": "nnue", "Hash": 16})
            for name in ("opening", "quiet_middlegame", "tactical", "pawn_endgame", "en_passant"):
                for repeat in range(3):
                    row = measure(engine, chess.Board(POSITIONS[name]), ms=300)
                    rows.append({"category": name, "repeat": repeat, **row})
        data["models"][model] = {"metadata": metadata(binary), "samples": rows}
    path.write_text(json.dumps(data, indent=2) + "\n")
    print("Saved", path)


if __name__ == "__main__":
    main()
