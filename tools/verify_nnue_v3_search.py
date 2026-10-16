"""Prove frozen classical/v2 parity and exercise independent v3 search state."""
from contextlib import ExitStack
import argparse
import json
from pathlib import Path
import time

import chess
import chess.engine

from tools.nnue_diagnosis import BASE_OPTIONS, capture, metadata, open_engine, positions
from tools.profile_nnue_diagnosis import canonical


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--full", action="store_true")
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    baseline = Path("artifacts/nnue-v3/v2/engine.exe")
    model = Path("engine/networks/v3/stockbear-v3-selected.sbnnue").resolve()
    result = {"baseline": metadata(baseline), "candidate": metadata(args.engine), "preserved_searches": [],
              "v3_searches": [], "cancellations": 0, "terminal_cases": 0}
    budgets = [("depth", 4), ("nodes", 100000)]
    if args.full:
        budgets += [("depth", 6), ("nodes", 400000), ("nodes", 1000000)]
    with ExitStack() as stack:
        a = stack.enter_context(open_engine(baseline))
        b = stack.enter_context(open_engine(args.engine))
        for key, option in a.options.items():
            assert b.options[key].default == option.default, key
        assert b.options["Evaluator"].default == "classical"
        for evaluator in ("classical", "nnue"):
            for engine in (a, b):
                engine.configure(BASE_OPTIONS | {"Evaluator": evaluator})
            for row in positions():
                for mode, budget in budgets:
                    original = capture(a, row, mode, budget)
                    candidate = capture(b, row, mode, budget)
                    assert canonical(original) == canonical(candidate), (evaluator, row["id"], mode, budget)
                    result["preserved_searches"].append({"position": row["id"], "evaluator": evaluator,
                        "mode": mode, "budget": budget, "identical": True, **canonical(candidate)})
                print("Preserved", evaluator, row["id"], flush=True)
        b.configure({"NNUEV3File": str(model), "Evaluator": "nnue_v3"})
        for row in positions():
            for mode, budget in (("depth", 4), ("nodes", 100000)):
                first = capture(b, row, mode, budget)
                second = capture(b, row, mode, budget)
                assert canonical(first) == canonical(second)
                b.configure({"NNUEIncremental": False})
                refreshed = capture(b, row, mode, budget)
                b.configure({"NNUEIncremental": True})
                result["v3_searches"].append({"position": row["id"], "mode": mode, "budget": budget,
                    "repeat_identical": True, "incremental": canonical(first), "full_refresh": canonical(refreshed),
                    "incremental_refresh_tree_identical": canonical(first) == canonical(refreshed)})
        first = capture(b, positions()[0], "depth", 4)
        for evaluator in ("classical", "nnue", "nnue_v3"):
            b.configure({"Evaluator": evaluator})
            capture(b, positions()[0], "depth", 3)
        assert canonical(first) == canonical(capture(b, positions()[0], "depth", 4))
        for row in positions()[::2]:
            with b.analysis(chess.Board(row["fen"]), chess.engine.Limit(time=1), game=object()) as job:
                time.sleep(.01)
                job.stop()
                assert job.wait().move in chess.Board(row["fen"]).legal_moves
            result["cancellations"] += 1
        terminals = [chess.Board(f) for f in ("7k/6Q1/5K2/8/8/8/8/8 b - - 0 1",
            "7k/5Q2/6K1/8/8/8/8/8 b - - 0 1", "7k/8/8/8/8/8/8/K7 w - - 0 1",
            "7k/8/8/8/8/8/8/KR6 w - - 100 1")]
        repeated = chess.Board()
        for move in ["g1f3", "g8f6", "f3g1", "f6g8"] * 2:
            repeated.push_uci(move)
        terminals.append(repeated)
        for board in terminals:
            played = b.play(board, chess.engine.Limit(depth=3), game=object(), info=chess.engine.INFO_ALL)
            assert not played.move
            assert played.info["score"].pov(board.turn).mate() == 0 if board.is_checkmate() else played.info["score"].white().score() == 0
            result["terminal_cases"] += 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print("Preserved", len(result["preserved_searches"]), "frozen searches; v3 repeat cases", len(result["v3_searches"]))


if __name__ == "__main__":
    main()
