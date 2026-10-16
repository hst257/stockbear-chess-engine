"""Serial, checkpointed final v3 verification, measurement and bounded matches."""
from contextlib import ExitStack
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys

from tools.benchmark_nnue_v3 import ROOT, MODEL, BUILDS
from tools.nnue_diagnosis import BASE_OPTIONS, capture, metadata, open_engine, positions, sha
from tools.profile_nnue_diagnosis import canonical
from tools.match_optimizations import write_record
from tools.verify_match_records import verify_record

ART = Path("artifacts/nnue-v3")
PYTORCH = str(Path("StockBear_NNUE_training/.venv/Scripts/python.exe").resolve())


def save(path, value):
    write_record(path, json.dumps(value, indent=2) + "\n")


def main() -> None:
    status_path = ART / "experiment-status.json"
    status = json.loads(status_path.read_text()) if status_path.exists() else {"completed": [], "state": "running"}
    if "error" in status:
        status.setdefault("recovered_errors", []).append({"stage": status.get("active"), "error": status.pop("error")})
    def run(name, command, env=None, cwd=None):
        print(name, flush=True)
        with (ART / (name + ".log")).open("a", encoding="utf-8") as stream:
            subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, check=True, env=env, cwd=cwd)
    def stage(name, operation):
        if name in status["completed"]: return
        status.update(state="running", active=name, utc=datetime.now(timezone.utc).isoformat())
        save(status_path, status)
        operation()
        status["completed"].append(name)
        status["active"] = None
        save(status_path, status)
    def profile():
        raw = json.loads((ROOT / "benchmark.json").read_text())["records"]
        records = []
        with open_engine(ART / "profile/engine.exe") as engine:
            engine.configure({"NNUEV3File": str(MODEL.resolve())} | BASE_OPTIONS | {"Evaluator": "nnue_v3"})
            for row in positions():
                record = capture(engine, row, "nodes", 400000)
                reference = next(r for r in raw if r["position"] == row["id"] and r["build"] == "v3"
                    and r["mode"] == "nodes" and r["budget"] == 400000 and r["repeat"] == 0)
                assert canonical(record) == canonical(reference)
                records.append(record)
        save(ROOT / "profile.json", {"build": metadata(ART / "profile/engine.exe"), "model_sha256": sha(MODEL),
            "records": records, "method": "Intrusive exclusive scoped clocks; exact 400k-node trees match release. Refresh scopes include root and affected king-bucket refreshes; feature scope covers state extraction, update includes delta application/copy. Scope time is not a production runtime percentage. No hardware cache counters or isolated copy attribution."})
    def native_desktop():
        env = os.environ.copy()
        env["SDL_VIDEODRIVER"], env["SDL_AUDIODRIVER"] = "windows", "dummy"
        run("desktop", [sys.executable, "-m", "app.main", "--engine", str(BUILDS["v3"]), "--mode", "engine",
             "--human-color", "black", "--evaluator", "nnue_v3", "--smoke-test", "120",
             "--screenshot", str(ROOT / "gui-native.png")], env)
        save(ROOT / "desktop.json", {"method": "Native Windows SDL launch and real UCI worker; app-rendered final frame, no manual input or OS screenshot claim",
            "exit_code": 0, "engine": metadata(BUILDS["v3"]), "model_sha256": sha(MODEL),
            "frame": "gui-native.png", "visually_inspected": False})
    def match(opponent, smoke=False):
        output = ROOT / f"match-v3-{opponent}.json"
        if output.exists():
            verify_record(output, check_binaries=True)
            return
        candidate_options = ROOT / "v3-options.json"
        other_options = ROOT / (opponent + "-options.json")
        save(candidate_options, {"NNUEV3File": str(MODEL.resolve())} | BASE_OPTIONS | {"Evaluator": "nnue_v3"})
        save(other_options, BASE_OPTIONS | {"Evaluator": "nnue" if opponent == "v2" else "classical"})
        command = [sys.executable, "-m", "tools.match_optimizations", "--comparison", "versions",
            "--engine", str(BUILDS["v3"]), "--opponent", str(BUILDS[opponent]),
            "--candidate-options", str(candidate_options), "--opponent-options", str(other_options),
            "--opening-book", "docs/nnue-v2-diagnosis/openings.json", "--games", "20", "--movetime", "500",
            "--max-plies", "240", "--retain-progress", "--output", str(output)]
        if output.with_suffix(".progress.json").exists(): command.append("--resume")
        if smoke: command += ["--max-new-games", "2"]
        run("smoke-v3-v2" if smoke else "match-v3-" + opponent, command)
        if not smoke:
            save(ROOT / ("replay-v3-" + opponent + ".json"), verify_record(output, check_binaries=True))
        else:
            progress = json.loads(output.with_suffix(".progress.json").read_text())
            assert len(progress["games"]) == 2
            save(ROOT / "smoke.json", {"completed": 2, "included_in_20": True, "legal_moves_and_uci_stable": True})
    try:
        stage("training-tests", lambda: run("training-tests", [PYTORCH, "-m", "pytest", "-q"], cwd="StockBear_NNUE_training"))
        stage("heldout-strata", lambda: run("heldout-strata", [PYTORCH, "-m", "tools.analyze_nnue_v3_training"]))
        env = os.environ.copy()
        env["SDL_VIDEODRIVER"], env["SDL_AUDIODRIVER"] = "dummy", "dummy"
        stage("gui", lambda: run("gui", [sys.executable, "-m", "tools.verify_gui_engine", "--evaluator", "nnue_v3",
            "--engine", str(BUILDS["v3"]), "--output", str(ROOT / "gui")], env))
        stage("desktop", native_desktop)
        stage("benchmark", lambda: run("benchmark", [sys.executable, "-m", "tools.benchmark_nnue_v3"]))
        stage("profile", profile)
        stage("quality", lambda: run("quality", [sys.executable, "-m", "tools.quality_nnue_v3"]))
        plan = ROOT / "match-plan.json"
        if not plan.exists():
            save(plan, {"games_v3_v2": 20, "ms_per_move": 500, "pairs": 10, "max_searched_plies": 240,
                "model_sha256": sha(MODEL), "opening_book_sha256": sha(Path("docs/nnue-v2-diagnosis/openings.json")),
                "classical_gate": "A separately bounded 20-game classical cohort is run only if v3 completed-game score versus v2 is at least 50%, with all correctness gates passed. No automatic expansion. Smoke pair included. Caps unknown.",
                "reused_pairs": "First 10 neutral opening pairs, nested within the prior 20-pair v2-classical cohort; compare only the matching subset for any cross-cohort trend, not independent confirmation.",
                "user_amendment": "make it 20 games, no need for 40"})
        stage("smoke", lambda: match("v2", True))
        stage("match-v3-v2", lambda: match("v2"))
        data = json.loads((ROOT / "match-v3-v2.json").read_text())
        score = data["summary"]["score_percent"]
        if score is not None and score >= 50:
            stage("match-v3-classical", lambda: match("classical"))
        else:
            save(ROOT / "classical-gate.json", {"run": False, "v3_v2_completed_game_score_percent": score,
                "reason": "Predetermined >=50% promise gate not met; preserve negative result without extra tournament games."})
        status.update(state="complete", active=None)
        save(status_path, status)
    except Exception as error:
        status.update(state="failed", error=repr(error))
        save(status_path, status)
        raise


if __name__ == "__main__":
    main()
