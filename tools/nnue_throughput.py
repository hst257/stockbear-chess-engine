"""Serial, checkpointed measurements for the frozen Compact v2 throughput study."""
from __future__ import annotations

from contextlib import ExitStack
import argparse
import hashlib
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time

from tools.nnue_diagnosis import BASE_OPTIONS, capture, metadata, open_engine, positions, sha
from tools.profile_nnue_diagnosis import canonical

ROOT = Path(os.environ.get("STOCKBEAR_THROUGHPUT_ROOT", "docs/nnue-v2-throughput"))
ART = Path(os.environ.get("STOCKBEAR_THROUGHPUT_ARTIFACTS", "artifacts/nnue-v2-throughput"))
MODEL = Path("engine/networks/v2/stockbear-v2-compact.sbnnue")
MODEL_SHA = "788b865a15dbdeeb3e03b7493f8155fd19d6c73b9b0873453ad16fba51a65aa7"


def save(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # One process owns this study. Checkpoints never replace earlier studies.
    temporary = path.with_suffix(path.suffix + ".tmp")
    large = len(data.get("records", [])) > 100
    temporary.write_text(json.dumps(data, indent=None if large else 2,
                                   separators=(",", ":") if large else None, allow_nan=False) + "\n",
                         encoding="utf-8", newline="\n")
    for attempt in range(20):
        try:
            temporary.replace(path)
            break
        except PermissionError:
            if attempt == 19:
                raise
            time.sleep(.05)


def run(name: str, command: list[str], env: dict | None = None) -> None:
    ART.mkdir(parents=True, exist_ok=True)
    print(name, flush=True)
    with (ART / (name + ".log")).open("a", encoding="utf-8") as stream:
        subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, check=True, env=env)


def build(label: str, flags: list[str] = (), micro: bool = False) -> Path:
    binary = ART / label / ("micro.exe" if micro else "engine.exe")
    if binary.exists():
        return binary
    env = os.environ.copy()
    env["ZIG_GLOBAL_CACHE_DIR"] = str(Path("engine/build/zig-cache").resolve())
    run("build-" + label + ("-micro" if micro else ""),
        [sys.executable, "tools/build_engine.py", "--nnue-model", str(MODEL),
         "--target", "nnue-bench" if micro else "engine", "--output", str(binary), *flags], env)
    return binary


def baseline() -> None:
    assert sha(MODEL) == MODEL_SHA
    path = ROOT / "baseline.json"
    if path.exists() and (ROOT / "initial-profile.json").exists() and (ROOT / "baseline-tests.txt").exists():
        frozen = json.loads(path.read_text())
        assert sha(ART / "baseline/engine.exe") == frozen["rebuilt"]["sha256"]
        assert sha(Path(frozen["preserved_classical_and_nnue"]["executable"])) == frozen["preserved_classical_and_nnue"]["sha256"]
        print("Retaining completed untouched baseline", flush=True)
        return
    if not path.exists():
        original = Path("artifacts/nnue-v2/final-compact/engine.exe")
        data = {"revision": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
                "model": str(MODEL), "model_sha256": sha(MODEL),
                "preserved_classical_and_nnue": metadata(original),
                "compiler_version": subprocess.check_output([sys.executable, "-m", "ziglang", "version"], text=True).strip(),
                "positions": positions(), "options": BASE_OPTIONS,
                "plan": {"nodes": [100000, 400000, 1000000], "time_ms": [50, 200, 1000],
                         "repeats": 5, "hash_mb": 16, "threads": 1,
                         "tournament": "60 games at 500ms; first 30 frozen neutral opening pairs, reverse colors; no expansion"}}
        snapshot = ART / "baseline-source"
        snapshot.mkdir(parents=True, exist_ok=True)
        for source in Path("engine/src").glob("*"):
            if source.is_file():
                (snapshot / source.name).write_bytes(source.read_bytes())
        save(path, data)
    binary = build("baseline")
    build("baseline", micro=True)
    from tools.verify_nnue_diagnosis import pe_text_sha
    data = json.loads(path.read_text())
    data["rebuilt"] = metadata(binary)
    data["text_sha256"] = pe_text_sha(binary)
    assert data["text_sha256"] == pe_text_sha(Path(data["preserved_classical_and_nnue"]["executable"]))
    save(path, data)
    if not (ROOT / "baseline-tests.txt").exists():
        env = os.environ.copy()
        env["CHESSLAB_TEST_ENGINE"] = str(Path("artifacts/nnue-v2-diagnosis/test-v1/engine.exe").resolve())
        env["CHESSLAB_DIAGNOSTIC_ENGINE"] = str(Path("artifacts/nnue-v2-diagnosis/counters/engine.exe").resolve())
        run("baseline-tests", [sys.executable, "-m", "pytest", "-q"], env)
        (ROOT / "baseline-tests.txt").write_bytes((ART / "baseline-tests.log").read_bytes())
    if not (ROOT / "initial-profile.json").exists():
        profile_initial()


def profile_initial() -> None:
    builds = {"release": ART / "baseline/engine.exe",
              "counters": Path("artifacts/nnue-v2-diagnosis/counters/engine.exe"),
              "clocks": Path("artifacts/nnue-v2-diagnosis/profile/engine.exe")}
    data = {"method": "Serial rotated paired fixed-work searches. Release wall is authoritative; scope clocks are intrusive and not production shares. No hardware cache counters available.",
            "builds": {k: metadata(v) for k, v in builds.items()}, "records": []}
    checkpoint = ROOT / "initial-profile-checkpoint.json"
    if checkpoint.exists():
        data = json.loads(checkpoint.read_text())
        assert all(data["builds"][k]["sha256"] == sha(v) for k, v in builds.items())
    done = {(r["repeat"], r["position"], r["budget"], r["build"]) for r in data["records"]}
    with ExitStack() as stack:
        engines = {k: stack.enter_context(open_engine(v)) for k, v in builds.items()}
        for engine in engines.values():
            engine.configure(BASE_OPTIONS | {"Evaluator": "nnue"})
        for repeat in range(2):
            for row in positions():
                for nodes in (100000, 400000, 1000000):
                    expected = None
                    for label in list(builds)[repeat:] + list(builds)[:repeat]:
                        key = (repeat, row["id"], nodes, label)
                        if key in done:
                            result = next(r for r in data["records"] if
                                          (r["repeat"], r["position"], r["budget"], r["build"]) == key)
                        else:
                            result = capture(engines[label], row, "nodes", nodes)
                            data["records"].append(result | {"build": label, "repeat": repeat})
                        if expected is None:
                            expected = canonical(result)
                        assert expected == canonical(result), (label, row["id"], nodes)
                    save(checkpoint, data)
                print("Profile", repeat, row["id"], flush=True)
    save(ROOT / "initial-profile.json", data)
    from collections import Counter
    clocks = [r for r in data["records"] if r["build"] == "clocks"]
    ns = Counter()
    for row in clocks:
        ns.update({k: v["ns"] for k, v in row["profile"]["categories"].items()})
    wall = {label: sum(r["wall_seconds"] for r in data["records"] if r["build"] == label) for label in builds}
    counts = Counter()
    for row in data["records"]:
        if row["build"] == "counters":
            counts.update({k: v for k, v in row["diagnostics"].items() if isinstance(v, int)})
    analysis = {"searches": len(data["records"]), "all_fixed_work_trees_identical": True,
                "wall_seconds": wall, "intrusive_ns": dict(ns.most_common()),
                "clock_overhead_ratio": wall["clocks"] / wall["release"],
                "counter_overhead_ratio": wall["counters"] / wall["release"],
                "counts": dict(counts), "allocations_inside_profile": sum(r["profile"]["allocations"] for r in clocks),
                "allocation_bytes_inside_profile": sum(r["profile"]["bytes"] for r in clocks),
                "ranked_hypotheses": [
                    "1: Move-derived update bookkeeping plus row arithmetic: highest NNUE scope; full sorted piece-feature lists copied and edited at every edge. Separate these with release differential candidates.",
                    "2: Forward head: measured scope, already transposed; preserve arithmetic and defer lower-level changes until bookkeeping is measured.",
                    "3: Fully unused states: bound by unused-leaf counter; test only intermediate-cached deferral, at most one materialization per live frame.",
                    "4: Copy alone: large scope-clock share is distorted by timer calls; cheap prior isolated copy and only 256 float bytes do not establish a primary bottleneck.",
                    "5: Root refresh and allocation: per-search setup, not per-node allocation; fresh TT construction is outside profile scopes and inside release wall.",
                    "Search/movegen/make/unmake/order/TT remain frozen. Hardware cache and branch attribution unavailable; no causal cache claims."],
                "decision_before_optimization": "First test a full-metadata merge, then a trusted NNUE-only state-feature path, then bounded intermediate-cached deferral and a scalar row-loop alternative. Preserve legacy update and exact row order; no model/search changes."}
    save(ROOT / "initial-analysis.json", analysis)
    print("Initial analysis complete", wall, flush=True)


def compare(label: str, repeats: int, budgets: list[int], timed: bool = False) -> None:
    path = ROOT / f"benchmark-{label}{'-time' if timed else ''}.json"
    data = json.loads(path.read_text()) if path.exists() else {
        "candidate": metadata(ART / label / "engine.exe"), "baseline": metadata(ART / "baseline/engine.exe"),
        "method": "Serial order alternating by trial and position; fresh game/TT; wall includes UCI and fresh table setup; engine seconds separately retained. Classical workload has its own tree.", "records": []}
    assert data["candidate"]["sha256"] == sha(ART / label / "engine.exe")
    assert data["baseline"]["sha256"] == sha(ART / "baseline/engine.exe")
    done = {(r["repeat"], r["position"], r["mode"], r["budget"], r["build"]) for r in data["records"]}
    with ExitStack() as stack:
        engines = {k: stack.enter_context(open_engine(v)) for k, v in {
            "baseline": ART / "baseline/engine.exe", label: ART / label / "engine.exe",
            "classical": ART / "baseline/engine.exe"}.items()}
        for name, engine in engines.items():
            engine.configure(BASE_OPTIONS | {"Evaluator": "classical" if name == "classical" else "nnue"})
        for repeat in range(repeats):
            for index, row in enumerate(positions()):
                for budget in budgets:
                    labels = list(engines)
                    offset = (repeat + index) % len(labels)
                    labels = labels[offset:] + labels[:offset]
                    for name in labels:
                        key = (repeat, row["id"], "time" if timed else "nodes", budget, name)
                        if key in done:
                            continue
                        before_cpu = process_cpu(engines[name].transport.get_pid())
                        record = capture(engines[name], row, key[2], budget)
                        after_cpu = process_cpu(engines[name].transport.get_pid())
                        record["cpu_seconds"] = after_cpu - before_cpu if before_cpu is not None and after_cpu is not None else None
                        data["records"].append(record | {"build": name, "repeat": repeat})
                    if not timed:
                        results = {r["build"]: r for r in data["records"] if
                                   (r["repeat"], r["position"], r["mode"], r["budget"]) == key[:4]}
                        assert canonical(results[label]) == canonical(results["baseline"]), (label, row["id"], budget)
                save(path, data)
                print("Benchmark", label, repeat, row["id"], flush=True)


def process_cpu(pid: int) -> float | None:
    """Windows process CPU time; includes the single worker and light UCI work."""
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        return None
    try:
        values = [wintypes.FILETIME() for _ in range(4)]
        if not kernel.GetProcessTimes(handle, *(ctypes.byref(v) for v in values)):
            return None
        return sum((v.dwHighDateTime << 32) | v.dwLowDateTime for v in values[2:]) / 1e7
    finally:
        kernel.CloseHandle(handle)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("baseline", "compare"))
    parser.add_argument("--label")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--budgets", type=int, nargs="+", default=[400000])
    parser.add_argument("--time", action="store_true")
    args = parser.parse_args()
    if args.phase == "baseline":
        baseline()
    else:
        compare(args.label, args.repeats, args.budgets, args.time)


if __name__ == "__main__":
    main()
