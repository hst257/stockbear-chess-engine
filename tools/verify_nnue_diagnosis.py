"""Verify optional diagnostics preserve release trees, model parity and UCI state."""
from __future__ import annotations

from contextlib import ExitStack
import json
from pathlib import Path
import struct
import subprocess
import time

import chess
import chess.engine

from tools.nnue_diagnosis import (ARTIFACTS, BASE_OPTIONS, DIAGNOSTIC, PROFILE, RELEASE, ROOT,
                                 capture, metadata, open_engine, prepare_suite, save, sha)
from tools.profile_nnue_diagnosis import canonical, verify_counts
from tools.validate_nnue_v2 import batch, corpus, errors


def pe_text_sha(path: Path) -> str:
    import hashlib
    image = path.read_bytes()
    pe, = struct.unpack_from("<I", image, 0x3c)
    assert image[pe:pe + 4] == b"PE\0\0"
    count, = struct.unpack_from("<H", image, pe + 6)
    optional_size, = struct.unpack_from("<H", image, pe + 20)
    for index in range(count):
        section = pe + 24 + optional_size + 40 * index
        if image[section:section + 8].rstrip(b"\0") == b".text":
            size, offset = struct.unpack_from("<II", image, section + 16)
            return hashlib.sha256(image[offset:offset + size]).hexdigest()
    raise ValueError("Missing PE text section")


def main() -> None:
    path = ROOT / "correctness.json"
    if path.exists():
        raise ValueError("Frozen correctness report exists")
    builds = {"preserved_release": RELEASE, "release_rebuilt": ARTIFACTS / "release/engine.exe",
              "counters": DIAGNOSTIC, "clock_profile": PROFILE, "ubsan": ARTIFACTS / "ubsan/engine.exe"}
    data = {"builds": {name: metadata(binary) for name, binary in builds.items()}, "searches": [], "integration": []}
    text = {name: pe_text_sha(builds[name]) for name in ("preserved_release", "release_rebuilt")}
    data["release_text_sha256"] = text
    data["release_machine_code_identical"] = text["preserved_release"] == text["release_rebuilt"]
    suite = prepare_suite()
    with ExitStack() as stack:
        engines = {name: stack.enter_context(open_engine(binary)) for name, binary in builds.items()}
        defaults = [{n: o.default for n, o in engine.options.items()} for engine in engines.values()]
        assert all(options == defaults[0] for options in defaults)
        assert defaults[0]["Evaluator"] == "classical"
        data["uci_defaults_identical"] = True
        for evaluator in ("classical", "nnue"):
            for engine in engines.values():
                engine.configure(BASE_OPTIONS | {"Evaluator": evaluator})
            for row in suite["positions"]:
                for mode, budget in (("depth", 4), ("nodes", 100000)):
                    results = {name: capture(engine, row, mode, budget) for name, engine in engines.items()}
                    expected = canonical(results["preserved_release"])
                    assert all(canonical(result) == expected for result in results.values()), (evaluator, row, mode)
                    for result in results.values():
                        if "diagnostics" in result:
                            if evaluator == "nnue":
                                verify_counts(result)
                            else:
                                assert all(v == 0 or v == [0] * 17 for v in result["diagnostics"].values())
                    data["searches"].append({"position": row["id"], "evaluator": evaluator, "mode": mode,
                                             "budget": budget, "all_builds_identical": True, **expected})
                print("Exact trees", evaluator, row["id"], flush=True)
        for name in ("counters", "ubsan"):
            engine = engines[name]
            a = capture(engine, suite["positions"][0], "depth", 4)
            engine.configure({"Evaluator": "classical"})
            classical = capture(engine, suite["positions"][0], "depth", 4)
            engine.configure({"Evaluator": "nnue"})
            b = capture(engine, suite["positions"][0], "depth", 4)
            assert canonical(a) == canonical(b)
            engine.configure({"Evaluator": "classical"})
            assert canonical(classical) == canonical(capture(engine, suite["positions"][0], "depth", 4))
            engine.configure({"Evaluator": "nnue"})
            for index, row in enumerate(suite["positions"][::2]):
                with engine.analysis(chess.Board(row["fen"]), chess.engine.Limit(time=1)) as pending:
                    time.sleep(.01)
                    pending.stop()
                    result = pending.wait()
                    assert result.move in chess.Board(row["fen"]).legal_moves
            terminal = [chess.Board("7k/6Q1/5K2/8/8/8/8/8 b - - 0 1"),
                        chess.Board("7k/5Q2/5K2/8/8/8/8/8 b - - 0 1"),
                        chess.Board("7k/8/8/8/8/8/8/K7 w - - 0 1"),
                        chess.Board("7k/8/8/8/8/8/8/KR6 w - - 100 1")]
            repeated = chess.Board()
            for uci in ["g1f3", "g8f6", "f3g1", "f6g8"] * 2:
                repeated.push_uci(uci)
            terminal.append(repeated)
            for board in terminal:
                result = engine.play(board, chess.engine.Limit(depth=3), info=chess.engine.INFO_ALL)
                assert result.move is None
                assert result.info["score"].white().is_mate() if board.is_checkmate() else result.info["score"].white().score() == 0
            data["integration"].append({"build": name, "cancellations": 12, "terminal_and_draws": 5,
                                         "switching_and_fresh_tt": True})
    rows = corpus()
    expected = batch(RELEASE.with_name("micro.exe"), rows, "scalar")
    goldens = json.loads(Path("engine/networks/v2/stockbear-v2-compact.golden.json").read_text(encoding="utf-8"))
    data["evaluation"] = {}
    for name in ("counters", "ubsan"):
        binary = builds[name].with_name("micro.exe")
        counter_oracle = json.loads(subprocess.check_output([str(binary.resolve()), "--diagnostics-verify"], text=True, timeout=10))
        actual = batch(binary, rows, "scalar")
        difference = errors(expected, actual)
        assert difference["max_cp"] == 0
        golden = batch(binary, [(r["fen"], "golden") for r in goldens], "scalar")
        golden_difference = errors([r["side_to_move_cp"] for r in goldens], golden)
        assert golden_difference["max_cp"] < .001
        transitions = json.loads(subprocess.check_output([str(binary.resolve()), "--verify", "scalar"], text=True, timeout=90))
        assert transitions["transitions"] > 30000 and transitions["nulls"] > 25000
        data["evaluation"][name] = {"metadata": metadata(binary), "heldout_random_extreme_parity": difference,
                                    "trained_golden_parity": golden_difference, "transitions": transitions,
                                    "synthetic_counter_oracle": counter_oracle}
    save(path, data)
    print("Verified", len(data["searches"]), "fixed-budget search cases across five builds", flush=True)


if __name__ == "__main__":
    main()
