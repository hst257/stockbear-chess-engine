"""Run the bounded diagnostic follow-up serially after all 190 match games finish."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback

from tools.nnue_diagnosis import ARTIFACTS, ROOT, save, sha


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wait-for-matches", action="store_true")
    parser.add_argument("--skip-builds", action="store_true")
    args = parser.parse_args()
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    status_path = ARTIFACTS / "pipeline-status.json"
    status = {"state": "waiting", "completed": [], "active": None}
    save(status_path, status)
    plan = json.loads((ROOT / "match-plan.json").read_text(encoding="utf-8"))
    paths = [Path(match["output"]) for match in plan["schedule"]]
    while not all(path.exists() and path.with_suffix(".pgn").exists() for path in paths):
        if not args.wait_for_matches:
            raise ValueError("Complete the fixed tournament schedule first, or use --wait-for-matches")
        time.sleep(5)
    assert sum(len(json.loads(path.read_text(encoding="utf-8"))["games"]) for path in paths) == 190
    assert sha(Path(plan["engine"])) == plan["engine_sha256"]
    environment = os.environ.copy()
    environment["ZIG_GLOBAL_CACHE_DIR"] = str(Path("engine/build/zig-cache").resolve())
    environment["CHESSLAB_DIAGNOSTIC_ENGINE"] = str((ARTIFACTS / "counters/engine.exe").resolve())

    def run(name: str, command: list[str], output: Path | None = None) -> None:
        if output and output.exists():
            print("Retaining completed", name, flush=True)
            return
        status.update(state="running", active=name)
        save(status_path, status)
        print("Starting", name, flush=True)
        log = ARTIFACTS / f"{name}.log"
        with log.open("a", encoding="utf-8") as stream:
            subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, env=environment, check=True)
        status["completed"].append(name)
        save(status_path, status)
        print("Completed", name, flush=True)

    try:
        run("match-verification", [sys.executable, "-m", "tools.verify_match_records", *map(str, paths),
                                   "--output", str(ROOT / "match-verification.json"), "--check-binaries"], ROOT / "match-verification.json")
        if not args.skip_builds:
            for label, flags in (("release", []), ("counters", ["--diagnostics"]),
                                 ("profile", ["--diagnostics", "--profile"]),
                                 ("ubsan", ["--diagnostics", "--sanitize", "undefined"])):
                for target, filename in (("engine", "engine.exe"), ("nnue-bench", "micro.exe")):
                    if target == "nnue-bench" and label not in ("counters", "ubsan"):
                        continue
                    binary = ARTIFACTS / label / filename
                    run(f"build-{label}-{target}", [sys.executable, "tools/build_engine.py", "--target", target,
                         "--nnue-model", plan["model"], "--output", str(binary), *flags])
        run("counter-oracle", [sys.executable, "-m", "pytest", "tests/test_nnue_diagnosis.py", "-q"])
        run("controlled-searches", [sys.executable, "-m", "tools.run_nnue_diagnosis_positions", "--phase", "searches"], ROOT / "controlled-searches.json")
        run("ablations", [sys.executable, "-m", "tools.run_nnue_diagnosis_positions", "--phase", "ablations"], ROOT / "ablations.json")
        run("stockfish-reference", [sys.executable, "-m", "tools.run_nnue_diagnosis_positions", "--phase", "reference"], ROOT / "stockfish-quality.json")
        run("static-score-diagnosis", [sys.executable, "-m", "tools.diagnose_nnue_score_scale"], ROOT / "static-score-diagnosis.json")
        run("capped-position-analysis", [sys.executable, "-m", "tools.diagnose_nnue_caps"], ROOT / "capped-position-analysis.json")
        run("accumulator-profile", [sys.executable, "-m", "tools.profile_nnue_diagnosis"], ROOT / "accumulator-profile.json")
        run("correctness", [sys.executable, "-m", "tools.verify_nnue_diagnosis"], ROOT / "correctness.json")
        run("pytest", [sys.executable, "-m", "pytest", "-q"])
        run("gui-workers", [sys.executable, "-m", "tools.verify_gui_engine", "--evaluator", "nnue", "--engine", plan["engine"], "--output", str(ARTIFACTS / "gui")], ARTIFACTS / "gui/gui-verification.json")
        preferred_plot_python = Path("StockBear_NNUE_training/.venv/Scripts/python.exe")
        plot_python = Path(os.environ.get("STOCKBEAR_DIAGNOSIS_PLOT_PYTHON", str(preferred_plot_python) if preferred_plot_python.exists() else sys.executable))
        run("analysis", [str(plot_python), "-m", "tools.analyze_nnue_diagnosis", "--plots"])
        run("record-audit", [sys.executable, "-m", "tools.audit_nnue_diagnosis_records"])
        status.update(state="complete", active=None)
        save(status_path, status)
    except Exception as error:
        status.update(state="failed", error=f"{type(error).__name__}: {error}", traceback=traceback.format_exc())
        save(status_path, status)
        raise


if __name__ == "__main__":
    main()
