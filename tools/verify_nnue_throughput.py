"""Exact frozen-reference trees, native arithmetic, model and UCI lifecycle gates."""
from __future__ import annotations

from contextlib import ExitStack
import argparse
import json
import subprocess
import time

import chess
import chess.engine

from tools.nnue_diagnosis import BASE_OPTIONS, capture, metadata, open_engine, positions, sha
from tools.nnue_throughput import ART, MODEL, MODEL_SHA, ROOT, save
from tools.profile_nnue_diagnosis import canonical
from tools.validate_nnue_v2 import batch, corpus, errors


def verify(label: str, full: bool) -> None:
    path = ROOT / f"correctness-{label}.json"
    binary = ART / label / "engine.exe"
    assert sha(MODEL) == MODEL_SHA
    data = {"baseline": metadata(ART / "baseline/engine.exe"), "candidate": metadata(binary),
            "model_sha256": sha(MODEL), "searches": [], "integration": []}
    with ExitStack() as stack:
        engines = {name: stack.enter_context(open_engine(exe)) for name, exe in
                   {"baseline": ART / "baseline/engine.exe", label: binary}.items()}
        defaults = [{name: option.default for name, option in engine.options.items()} for engine in engines.values()]
        assert defaults[0] == defaults[1] and defaults[0]["Evaluator"] == "classical"
        data["uci_defaults_identical"] = True
        budgets = [("depth", 4), ("nodes", 100000)]
        if full:
            budgets += [("depth", 6), ("nodes", 400000), ("nodes", 1000000)]
        for evaluator in ("classical", "nnue"):
            for engine in engines.values():
                engine.configure(BASE_OPTIONS | {"Evaluator": evaluator})
            for row in positions():
                for mode, budget in budgets:
                    records = {name: capture(engine, row, mode, budget) for name, engine in engines.items()}
                    assert canonical(records["baseline"]) == canonical(records[label]), (evaluator, row["id"], mode, budget)
                    data["searches"].append({"position": row["id"], "evaluator": evaluator, "mode": mode,
                                             "budget": budget, "identical": True, **canonical(records[label])})
                print("Parity", label, evaluator, row["id"], flush=True)
        engine = engines[label]
        for kernel in ("scalar", "reference", "quant", "auto"):
            for instance in engines.values():
                instance.configure({"NNUEKernel": kernel, "Evaluator": "nnue"})
            for row in positions()[::4]:
                expected = capture(engines["baseline"], row, "depth", 3)
                assert canonical(expected) == canonical(capture(engine, row, "depth", 3))
        engine.configure({"NNUEKernel": "scalar"})
        first = capture(engine, positions()[0], "depth", 4)
        engine.configure({"Evaluator": "classical"})
        capture(engine, positions()[0], "depth", 3)
        engine.configure({"Evaluator": "nnue"})
        assert canonical(first) == canonical(capture(engine, positions()[0], "depth", 4))
        for row in positions()[::2]:
            with engine.analysis(chess.Board(row["fen"]), chess.engine.Limit(time=1), game=object()) as pending:
                time.sleep(.01)
                pending.stop()
                result = pending.wait()
                assert result.move in chess.Board(row["fen"]).legal_moves
        terminals = [chess.Board(fen) for fen in (
            "7k/6Q1/5K2/8/8/8/8/8 b - - 0 1", "7k/5Q2/5K2/8/8/8/8/8 b - - 0 1",
            "7k/8/8/8/8/8/8/K7 w - - 0 1", "7k/8/8/8/8/8/8/KR6 w - - 100 1")]
        repeated = chess.Board()
        for move in ["g1f3", "g8f6", "f3g1", "f6g8"] * 2:
            repeated.push_uci(move)
        terminals.append(repeated)
        for board in terminals:
            result = engine.play(board, chess.engine.Limit(depth=3), game=object(), info=chess.engine.INFO_ALL)
            assert not result.move
            assert result.info["score"].white().is_mate() if board.is_checkmate() else result.info["score"].white().score() == 0
        data["integration"] = {"cancellations": 12, "terminal_draw_cases": 5, "kernel_cases": 24,
                               "evaluator_switch_and_fresh_root": True}
    micro = binary.with_name("micro.exe")
    if micro.exists():
        transitions = json.loads(subprocess.check_output([str(micro.resolve()), "--verify-throughput", "scalar"], text=True, timeout=120))
        assert transitions["transitions"] > 30000 and transitions["nulls"] > 25000 and transitions["bitwise_exact"]
        data["move_transition_oracle"] = transitions
        for kernel in ("scalar", "quant"):
            data["generic_transitions_" + kernel] = json.loads(subprocess.check_output(
                [str(micro.resolve()), "--verify", kernel], text=True, timeout=120))
        if full:
            rows = corpus()
            expected = batch(ART / "baseline/micro.exe", rows, "scalar")
            actual = batch(micro, rows, "scalar")
            difference = errors(expected, actual)
            assert difference["max_cp"] == 0
            data["heldout_random_extreme"] = difference
            goldens = json.loads(MODEL.with_suffix(".golden.json").read_text())
            difference = errors([r["side_to_move_cp"] for r in goldens],
                                batch(micro, [(r["fen"], "golden") for r in goldens], "scalar"))
            assert difference["max_cp"] < .001
            data["golden"] = difference
    save(path, data)
    print("Passed", label, len(data["searches"]), "exact deterministic cases", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("label")
    parser.add_argument("--full", action="store_true")
    args = parser.parse_args()
    verify(args.label, args.full)
