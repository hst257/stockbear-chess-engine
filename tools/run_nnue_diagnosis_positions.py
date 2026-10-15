"""Run controlled search, single-switch ablations and offline reference analysis.

Do not run this while tournaments or other heavy benchmarks are active.
All outputs are fresh or resumed from atomic progress files.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import json
from pathlib import Path
import time

import chess
import chess.engine

from tools.nnue_diagnosis import (ABLATIONS, BASE_OPTIONS, RELEASE, ROOT, STOCKFISH,
                                 capture, metadata, open_engine, prepare_suite, save, score_value, sha)


def load_progress(path: Path, expected: dict) -> tuple[dict, bool]:
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["identity"] == expected
        return data, True
    progress = path.with_suffix(".progress.json")
    if progress.exists():
        data = json.loads(progress.read_text(encoding="utf-8"))
        assert data["identity"] == expected
        return data, False
    return {"identity": expected, "records": []}, False


def checkpoint(path: Path, data: dict, final: bool = False) -> None:
    save(path if final else path.with_suffix(".progress.json"), data)
    if final:
        path.with_suffix(".progress.json").unlink(missing_ok=True)


def run_searches(ablation: bool = False) -> None:
    suite = prepare_suite()
    plan = suite["ablation_plan" if ablation else "search_plan"]
    configs = ABLATIONS if ablation else {"production": {}}
    path = ROOT / ("ablations.json" if ablation else "controlled-searches.json")
    identity = {"engine_sha256": sha(RELEASE), "suite_sha256": sha(ROOT / "positions.json"), "plan": plan,
                "options": BASE_OPTIONS, "configurations": configs}
    data, complete = load_progress(path, identity)
    if complete:
        print("Already complete", path, len(data["records"]), flush=True)
        return
    data.setdefault("metadata", metadata(RELEASE))
    data["method"] = "Serial searches, fresh per-go TT and private history; alternating evaluator order and rotated configurations by repetition. Final totals include unfinished work; depth/score/PV use only completed iterations. No production behavior changed."
    done = {(r["position"], r["evaluator"], r["configuration"], r["mode"], r["budget"], r["repeat"]) for r in data["records"]}
    budgets = (("time", plan["time_ms"]), ("nodes", plan["nodes"])) if ablation else tuple((mode, plan[key]) for mode, key in (("time", "time_ms"), ("nodes", "nodes"), ("depth", "depth")))
    if ablation:
        budgets = tuple((mode, [budget]) for mode, budget in budgets)
    with ExitStack() as stack:
        engines = {name: stack.enter_context(open_engine(RELEASE)) for name in ("nnue", "classical")}
        data.setdefault("defaults", {name: option.default for name, option in engines["nnue"].options.items()})
        for repeat in range(plan["repeats"]):
            names = list(configs)
            names = names[repeat % len(names):] + names[:repeat % len(names)]
            for index, row in enumerate(suite["positions"]):
                for configuration in names:
                    for mode, values in budgets:
                        for budget in values:
                            evaluators = ("classical", "nnue") if (index + repeat) % 2 else ("nnue", "classical")
                            for evaluator in evaluators:
                                key = (row["id"], evaluator, configuration, mode, budget, repeat)
                                if key in done:
                                    continue
                                engine = engines[evaluator]
                                engine.configure(BASE_OPTIONS | {"Evaluator": evaluator} |
                                                 {option: True for config in ABLATIONS.values() for option in config} |
                                                 configs[configuration])
                                result = capture(engine, row, mode, budget)
                                disabled_counters = {"UseLMR": ("lmr_attempts", "lmr_searches", "lmr_researches"),
                                                     "UseNullMovePruning": ("null_attempts", "null_cutoffs"),
                                                     "UseFutility": ("futility_prunes",),
                                                     "UseReverseFutility": ("reverse_futility_cutoffs",),
                                                     "UseAspirationWindows": ("aspiration_attempts", "aspiration_retries")}
                                for option in configs[configuration]:
                                    assert all(result["counters"][key] == 0 for key in disabled_counters[option]), (configuration, result)
                                result.update(evaluator=evaluator, configuration=configuration, repeat=repeat,
                                              overrides=BASE_OPTIONS | {"Evaluator": evaluator} | configs[configuration])
                                data["records"].append(result)
                                done.add(key)
                checkpoint(path, data)
                print(path.stem, "repeat", repeat + 1, row["id"], "records", len(done), flush=True)
    checkpoint(path, data, final=True)


def reference_search(engine: chess.engine.SimpleEngine, board: chess.Board, root_color: chess.Color, nodes: int) -> dict:
    outcome = board.outcome(claim_draw=True)
    if outcome is not None:
        return {"terminal": outcome.result(), "termination": outcome.termination.name,
                "root_points": .5 if outcome.winner is None else float(outcome.winner == root_color),
                "score_root": {"cp": 0 if outcome.winner is None else None, "mate": None},
                "move": None, "pv": [], "nodes": 0, "wall_seconds": 0}
    engine.configure({"Clear Hash": None})
    started = time.perf_counter()
    info = engine.analyse(board, chess.engine.Limit(nodes=nodes), game=object(), info=chess.engine.INFO_ALL)
    replay = board.copy()
    for move in info["pv"]:
        assert move in replay.legal_moves
        replay.push(move)
    return {"score_root": score_value(info["score"].pov(root_color)), "depth": info["depth"],
            "nodes": info["nodes"], "seconds": info["time"], "nps": info.get("nps"),
            "wall_seconds": time.perf_counter() - started, "move": info["pv"][0].uci(),
            "pv": [m.uci() for m in info["pv"]]}


def run_reference() -> None:
    suite = prepare_suite()
    sources = [ROOT / name for name in ("controlled-searches.json", "ablations.json")]
    candidates: dict[str, set[str]] = {row["id"]: set() for row in suite["positions"]}
    for source in sources:
        for record in json.loads(source.read_text(encoding="utf-8"))["records"]:
            candidates[record["position"]].add(record["move"])
    plan = suite["reference_plan"]
    identity = {"engine_sha256": sha(STOCKFISH), "suite_sha256": sha(ROOT / "positions.json"),
                "source_sha256": {str(p): sha(p) for p in sources}, "plan": plan}
    path = ROOT / "stockfish-quality.json"
    data, complete = load_progress(path, identity)
    if complete:
        print("Already complete", path, flush=True)
        return
    data.setdefault("metadata", metadata(STOCKFISH))
    data["method"] = "SF root chooses reference move at 300k nodes. Every distinct candidate including that reference move is analyzed from its child at 300k nodes, fresh hash, one thread, Hash64, no TB, original root-side perspective. Child-vs-child score delta is primary; root-vs-child context is also retained. Negative raw losses indicate bounded-budget inconsistency, not negative error. Mates and terminal outcomes stay separate; probability transforms are descriptive, not calibrated win probabilities."
    previous = {row["position"]: row for row in data["records"]}
    with open_engine(STOCKFISH) as engine:
        data["engine_id"] = engine.id
        assert "Stockfish 19" in engine.id.get("name", ""), engine.id
        options = {"Threads": 1, "Hash": 64, "SyzygyPath": "", "UCI_LimitStrength": False}
        engine.configure(options)
        data["overrides"] = options
        data["defaults"] = {name: option.default for name, option in engine.options.items()}
        for row in suite["positions"]:
            board = chess.Board(row["fen"])
            if row["id"] not in previous:
                root = reference_search(engine, board, board.turn, plan["nodes"])
                item = {"position": row["id"], "fen": row["fen"], "category": row["category"], "root": root, "candidates": {}}
                data["records"].append(item)
                previous[row["id"]] = item
                checkpoint(path, data)
            item = previous[row["id"]]
            for move in sorted(candidates[row["id"]] | {item["root"]["move"]}):
                if move in item["candidates"]:
                    continue
                child = board.copy()
                child.push_uci(move)
                item["candidates"][move] = reference_search(engine, child, board.turn, plan["nodes"])
                checkpoint(path, data)
            print("Stockfish", row["id"], len(item["candidates"]), "distinct moves", flush=True)
    checkpoint(path, data, final=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("searches", "ablations", "reference", "all"), default="all")
    args = parser.parse_args()
    if args.phase in ("searches", "all"):
        run_searches()
    if args.phase in ("ablations", "all"):
        run_searches(ablation=True)
    if args.phase in ("reference", "all"):
        run_reference()


if __name__ == "__main__":
    main()
