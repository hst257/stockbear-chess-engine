"""Run remaining serial counters, preserve/rebuild the app runtime, and launch v2."""
from contextlib import ExitStack
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from app.engine_client import DEFAULT_ENGINE
from tools.nnue_diagnosis import BASE_OPTIONS, capture, metadata, open_engine, positions, sha
from tools.nnue_throughput import ART, ROOT, run, save
from tools.profile_nnue_diagnosis import canonical


def main() -> None:
    status = json.loads((ART / "final-status.json").read_text())
    assert status["state"] == "complete" and "validation-35games-500ms" in status["completed"]
    work = json.loads((ROOT / "work-counters.json").read_text()) if (ROOT / "work-counters.json").exists() else {}
    if len(work.get("records", [])) != 72 or len(work.get("summary", [])) != 3:
        run("all-budget-work", [sys.executable, "-m", "tools.work_nnue_throughput"])
    backup = ART / "runtime-before/engine.exe"
    backup.parent.mkdir(parents=True, exist_ok=True)
    if not backup.exists():
        shutil.copy2(DEFAULT_ENGINE, backup)
        shutil.copy2(DEFAULT_ENGINE.with_suffix(".build.json"), backup.with_suffix(".build.json"))
    old = json.loads(backup.with_suffix(".build.json").read_text())
    runtime_report = ROOT / "application-runtime.json"
    if not runtime_report.exists():
        env = os.environ.copy()
        env["ZIG_GLOBAL_CACHE_DIR"] = str(Path("engine/build/zig-cache").resolve())
        run("build-application-runtime", [sys.executable, "tools/build_engine.py", "--nnue-update", "compact",
                                         "--nnue-model", old["nnue"]["model"], "--output", str(DEFAULT_ENGINE)], env)
        actual = json.loads(DEFAULT_ENGINE.with_suffix(".build.json").read_text())
        assert actual["nnue"]["sha256"] == old["nnue"]["sha256"]
        data = {"before": metadata(backup), "after": metadata(DEFAULT_ENGINE), "same_model_sha256": actual["nnue"]["sha256"],
                "note": "Normal application runtime keeps its original v1 model and classical default. All v2 measurements/desktop launch explicitly use the separately preserved final Compact v2 build.", "searches": []}
        with ExitStack() as stack:
            a = stack.enter_context(open_engine(backup))
            b = stack.enter_context(open_engine(DEFAULT_ENGINE))
            for evaluator in ("classical", "nnue"):
                for engine in (a, b):
                    engine.configure(BASE_OPTIONS | {"Evaluator": evaluator})
                for row in positions()[::3]:
                    for mode, budget in (("depth", 4), ("nodes", 100000)):
                        expected, result = capture(a, row, mode, budget), capture(b, row, mode, budget)
                        assert canonical(expected) == canonical(result)
                        data["searches"].append({"position": row["id"], "evaluator": evaluator,
                                                 "mode": mode, "budget": budget, "identical": True})
        save(runtime_report, data)
    else:
        assert sha(DEFAULT_ENGINE) == json.loads(runtime_report.read_text())["after"]["sha256"]
    desktop = ROOT / "desktop-verification.json"
    if not desktop.exists():
        env = os.environ.copy()
        env["SDL_VIDEODRIVER"] = "windows"
        env["SDL_AUDIODRIVER"] = "dummy"
        run("native-desktop", [sys.executable, "-m", "app.main", "--mode", "engine", "--human-color", "black",
             "--evaluator", "nnue", "--engine", str(ART / "final/engine.exe"), "--smoke-test", "120",
             "--screenshot", str(ROOT / "gui-desktop.png")], env)
        assert (ROOT / "gui-desktop.png").is_file()
        save(desktop, {"method": "Native Windows SDL application launch with real UCI worker; final rendered frame saved by app, not an OS desktop screenshot. No mouse/keyboard interaction claimed.",
             "engine": metadata(ART / "final/engine.exe"), "evaluator": "nnue", "human_color": "black",
             "frames": 120, "process_exit": 0, "frame": "gui-desktop.png", "visually_inspected": False})


if __name__ == "__main__":
    main()
