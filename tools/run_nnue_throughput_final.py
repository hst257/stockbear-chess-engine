"""Serial final correctness, sanitizer, release benchmark and bounded match pipeline."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import traceback

from tools.nnue_diagnosis import metadata, sha
from tools.nnue_throughput import ART, ROOT, MODEL, MODEL_SHA, build, compare, run, save
from tools.verify_nnue_throughput import verify
from tools.analyze_nnue_throughput import summarize
from tools.duel_nnue_throughput import duel


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strategy", required=True, choices=("compact", "compact-small"))
    parser.add_argument("--matches", action="store_true")
    args = parser.parse_args()
    status_path = ART / "final-status.json"
    status = json.loads(status_path.read_text()) if status_path.exists() else {
        "strategy": args.strategy, "completed": [], "state": "starting"}
    assert status["strategy"] == args.strategy
    if status.get("state") == "failed":
        status.setdefault("prior_failures", []).append({key: status[key] for key in ("active", "error", "traceback") if key in status})
        status.pop("error", None)
        status.pop("traceback", None)

    def stage(name, action):
        if name in status["completed"]:
            print("Retaining", name, flush=True)
            return
        status.update(state="running", active=name)
        save(status_path, status)
        print("Starting", name, flush=True)
        action()
        status["completed"].append(name)
        save(status_path, status)
        print("Completed", name, flush=True)

    flags = ["--nnue-update", args.strategy]
    env = os.environ.copy()
    env["ZIG_GLOBAL_CACHE_DIR"] = str(Path("engine/build/zig-cache").resolve())
    env["CHESSLAB_TEST_ENGINE"] = str((ART / "test-v1/engine.exe").resolve())
    env["CHESSLAB_THROUGHPUT_MICRO"] = str((ART / "final/micro.exe").resolve())
    env["CHESSLAB_DIAGNOSTIC_ENGINE"] = str((ART / "optimized-counters/engine.exe").resolve())

    def full_tests():
        run("final-pytest", [sys.executable, "-m", "pytest", "-q"], env)
        (ROOT / "final-tests.txt").write_bytes((ART / "final-pytest.log").read_bytes())

    def address_sanitizer():
        probes_path = ROOT / "asan-probes.json"
        prior_log = ART / "build-asan.log"
        if probes_path.exists() and prior_log.exists():
            probes = json.loads(probes_path.read_text())["probes"]
            log = prior_log.read_text()
            if ("duplicate symbol: vtable" in log and all(p["build_exit"] != 0 for p in probes)
                    and "duplicate symbol: vtable" in probes[0]["build_log"]):
                save(ROOT / "asan-availability.json", {"available": False, "build_log": log,
                     "independent_probe": "asan-probes.json", "status": "Zig Windows standard-library ASan linker failure reproduced without engine; alternate MinGW ASan runtime unavailable. No ASan pass claimed."})
                return
        try:
            binary = build("asan", flags + ["--sanitize", "address"])
        except subprocess.CalledProcessError:
            log = (ART / "build-asan.log").read_text()
            # Unsupported target/runtime is a tooling limit, not a sanitizer pass.
            if not any(term in log.lower() for term in ("unsupported", "not supported", "unable to find", "compiler-rt", "cannot find")):
                raise
            save(ROOT / "asan-availability.json", {"available": False, "build_log": log,
                 "status": "Compiler/target runtime unavailable; no ASan execution or pass claimed."})
        else:
            build("asan", flags + ["--sanitize", "address"], micro=True)
            verify("asan", True)
            save(ROOT / "asan-availability.json", {"available": True, "verification": "correctness-asan.json"})

    def games():
        options = ROOT / "nnue-options.json"
        save(options, {"Evaluator": "nnue", "Hash": 16, "NNUEKernel": "scalar", "NNUEIncremental": True})
        book = Path("docs/nnue-v2-diagnosis/openings.json")
        output = ROOT / "validation-500ms.json"
        plan = {"candidate": metadata(ART / "final/engine.exe"), "baseline": metadata(ART / "baseline/engine.exe"),
                "book": str(book), "book_sha256": sha(book), "games": 60, "opening_pairs": 30,
                "milliseconds": 500, "max_searched_plies": 240,
                "options": json.loads(options.read_text()),
                "method": "First 30 frozen neutral opening pairs, reverse colors. First pair is smoke test retained in total. No extensions. Capped games unfinished, paired uncertainty, no definitive Elo claim."}
        save(ROOT / "validation-plan.json", plan)
        command = [sys.executable, "-m", "tools.match_optimizations", "--comparison", "versions", "--games", "60",
                   "--movetime", "500", "--max-plies", "240", "--seed", "20261017", "--opening-book", str(book),
                   "--engine", str(ART / "final/engine.exe"), "--opponent", str(ART / "baseline/engine.exe"),
                   "--candidate-options", str(options), "--opponent-options", str(options), "--output", str(output), "--retain-progress"]
        if not output.exists():
            progress = output.with_suffix(".progress.json")
            # Run the first scheduled pair as a bounded smoke checkpoint.
            if not progress.exists():
                run("validation-smoke", command + ["--max-new-games", "2"], env)
                smoke = json.loads(progress.read_text())
                assert len(smoke["games"]) == 2
                assert all(s["nodes"] > 0 and s["depth"] > 0 for g in smoke["games"] for s in g["searches"])
                save(ROOT / "validation-smoke.json", {"games": 2, "included_in_final_60": True,
                     "legal_nonzero_searches": all(s["nodes"] > 0 and s["depth"] > 0 for g in smoke["games"] for s in g["searches"])})
            run("validation-games", command + ["--resume"], env)
        from tools.verify_match_records import verify_record
        save(ROOT / "validation-replay.json", verify_record(output, check_binaries=True))

    try:
        assert sha(MODEL) == MODEL_SHA
        stage("build-final", lambda: (build("final", flags), build("final", flags, micro=True)))
        stage("exact-final", lambda: verify("final", True))
        stage("build-ubsan", lambda: (build("ubsan", flags + ["--sanitize", "undefined"]),
                                     build("ubsan", flags + ["--sanitize", "undefined"], micro=True)))
        stage("exact-ubsan", lambda: verify("ubsan", True))
        stage("asan", address_sanitizer)
        stage("build-current-counters", lambda: (build("optimized-counters", flags + ["--diagnostics"]),
                                                build("optimized-counters", flags + ["--diagnostics"], micro=True)))
        stage("build-test-v1", lambda: run("build-test-v1", [sys.executable, "tools/build_engine.py", *flags,
                                          "--output", str(ART / "test-v1/engine.exe")], env))
        stage("full-tests", full_tests)
        stage("fixed-nodes", lambda: (compare("final", 5, [100000, 400000, 1000000]), summarize(ROOT / "benchmark-final.json")))
        stage("fixed-time", lambda: (compare("final", 5, [50, 200, 1000], True), summarize(ROOT / "benchmark-final-time.json")))
        stage("classical-release", lambda: duel("baseline", "final", "classical", 5))
        stage("detailed-profile", lambda: run("detailed-profile", [sys.executable, "-m", "tools.profile_nnue_throughput", "--strategy", args.strategy], env))
        stage("gui", lambda: run("gui", [sys.executable, "-m", "tools.verify_gui_engine", "--evaluator", "nnue", "--engine", str(ART / "final/engine.exe"),
                                             "--output", str(ART / "gui")], env))
        if args.matches:
            stage("validation-60games-500ms", games)
        status.update(state="complete", active=None)
        save(status_path, status)
    except Exception as error:
        status.update(state="failed", error=f"{type(error).__name__}: {error}", traceback=traceback.format_exc())
        save(status_path, status)
        raise


if __name__ == "__main__":
    main()
