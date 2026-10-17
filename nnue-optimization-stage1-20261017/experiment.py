"""Isolated Stage 1 builds, correctness gates and bounded paired benchmarks."""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import ctypes
import difflib
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
PROFILE = REPO / "nnue-profiling-20261017"
ART = ROOT / "artifacts"
sys.path.insert(0, str(REPO))
from tools import nnue_showdown as common
from tools.nnue_diagnosis import capture, open_engine
from tools.profile_nnue_diagnosis import canonical

PYTHON = REPO / ".venv/Scripts/python.exe"


def save(name: str, value) -> None:
    common.save(ROOT / name, value)


def pin() -> None:
    api = ctypes.windll.kernel32
    api.GetCurrentProcess.restype = ctypes.c_void_p
    api.SetProcessAffinityMask.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
    if not api.SetProcessAffinityMask(api.GetCurrentProcess(), 1):
        raise ctypes.WinError()


def command(args: list[str], name: str, timeout: int = 180) -> str:
    env = dict(os.environ, ZIG_GLOBAL_CACHE_DIR=str(ART / "zig-cache"))
    result = subprocess.run(args, cwd=REPO, env=env, capture_output=True,
                            text=True, timeout=timeout)
    (ART / (name + ".log")).write_text(result.stdout + result.stderr, encoding="utf-8")
    if result.returncode:
        raise RuntimeError(f"Failed {name}; see artifacts/{name}.log")
    return result.stdout


def prepare() -> None:
    if (ROOT / "plan.json").exists():
        raise ValueError("Frozen plan exists; do not overwrite the experiment")
    ART.mkdir(parents=True, exist_ok=True)
    protected = common.load(PROFILE / "preservation-before.json")
    for path in PROFILE.rglob("*"):
        if path.is_file() and not {"artifacts", "__pycache__"}.intersection(path.relative_to(PROFILE).parts):
            protected[path.relative_to(REPO).as_posix()] = common.sha(path)
    for name in ("NNUE_PROFILING_REPORT.md", "NNUE_OPTIMIZATION_ROADMAP.md"):
        protected[name] = common.sha(REPO / name)
    save("preservation-before.json", protected)
    for path, expected in protected.items():
        assert common.sha(REPO / path) == expected, path
    shutil.copytree(REPO / "engine/src", ART / "baseline-source")
    shutil.copytree(REPO / "engine/src", ART / "variant-source")
    shutil.copytree(PROFILE / "artifacts/micro/generated", ART / "generated")
    shutil.copy2(ROOT / "stage1_head.hpp", ART / "variant-source/stage1_head.hpp")
    original = (ART / "baseline-source/nnue.cpp").read_text()
    variant = original.replace('#include <cstdlib>', '#include <cstdlib>\n#include "stage1_head.hpp"')
    variant = variant.replace('AUTO, REFERENCE, SCALAR, QUANT', 'AUTO, REFERENCE, SCALAR, QUANT, CLIP')
    variant = variant.replace('"scalar", "quant"}', '"scalar", "quant", "clip"}')
    variant = variant.replace('i < 4;', 'i < 5;').replace('i >= 3 &&', 'i == 3 &&')
    variant = variant.replace('if (selected_kernel == Kernel::AUTO) return "scalar";',
        'if (selected_kernel == Kernel::AUTO) return "scalar";\n    if (selected_kernel == Kernel::CLIP && !nnue_simd_available()) return "scalar";')
    variant = variant.replace('if (nnue_quantized()) return quantized_head(board, accumulator);',
        'if (nnue_quantized()) return quantized_head(board, accumulator);\n'
        '#if (defined(__x86_64__) || defined(__i386__)) && (defined(__GNUC__) || defined(__clang__))\n'
        '    if (selected_kernel == Kernel::CLIP && nnue_simd_available())\n'
        '        return stage1::head(board, accumulator);\n#endif')
    assert variant != original and variant.count('return stage1::head') == 1
    (ART / "variant-source/nnue.cpp").write_text(variant)
    main = (ART / "baseline-source/main.cpp").read_text()
    modified_main = main.replace('var scalar var quant"', 'var scalar var quant var clip"')
    assert modified_main != main
    (ART / "variant-source/main.cpp").write_text(modified_main)
    patches = []
    for name in ("nnue.cpp", "main.cpp"):
        a = (ART / "baseline-source" / name).read_text().splitlines(keepends=True)
        b = (ART / "variant-source" / name).read_text().splitlines(keepends=True)
        patches.extend(difflib.unified_diff(a, b, fromfile="a/engine/src/" + name,
                                          tofile="b/engine/src/" + name))
    (ROOT / "variant.patch").write_text("".join(patches))
    shutil.copy2(PROFILE / "positions.json", ROOT / "positions.json")
    golden_paths = [REPO / "engine/networks/stockbear-compact.golden.json",
                    REPO / "engine/networks/v2/stockbear-v2-compact.golden.json"]
    golden_fens = list(dict.fromkeys(row["fen"] for path in golden_paths for row in common.load(path)))
    (ROOT / "golden-fens.txt").write_text("\n".join(golden_fens) + "\n")
    prior = common.load(PROFILE / "config.json")
    plan = {"network": prior["network"], "network_sha256": prior["network_sha256"],
            "options": dict(prior["options"], Evaluator="nnue"), "seed": 20261017,
            "profile": "Quiet / Eco, last confirmed by user; no power changes",
            "affinity_mask": 1, "repeats": 7, "maximum_repeats": 10,
            "budgets": [["nodes", 200000], ["nodes", 1000000], ["time", 100], ["time", 500], ["time", 1000]],
            "variant": "SIMD branchless input preclip; original dense/output order",
            "source_revision": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
            "golden_fens": len(golden_fens)}
    assert common.sha(Path(plan["network"])) == plan["network_sha256"]
    save("plan.json", plan)
    print("Prepared isolated sources and frozen plan", flush=True)


def build() -> None:
    meta = common.load(PROFILE / "build-micro.json")
    old = meta["flags"]
    flags = old[:old.index(str(REPO / "engine/tests/benchmark_nnue.cpp"))]
    for label in ("baseline", "variant"):
        source = ART / (label + "-source")
        base = [str(ART / "generated") if s == str(PROFILE / "artifacts/micro/generated")
                else str(source) if s == str(REPO / "engine/src") else s for s in flags]
        for target in ("engine", "micro", "oracle"):
            out = ART / label / (target + ".exe")
            out.parent.mkdir(parents=True, exist_ok=True)
            if target == "engine":
                sources = [source / name for name in ("main.cpp", "search.cpp", "evaluation.cpp", "nnue.cpp", "nnue_v3.cpp")]
            elif target == "micro":
                sources = [ROOT / "head_harness.cpp", source / "nnue.cpp"]
            else:
                sources = [REPO / "engine/tests/benchmark_nnue.cpp"] + [source / name for name in ("search.cpp", "evaluation.cpp", "nnue.cpp", "nnue_v3.cpp")]
            args = meta["compiler"] + base + [str(s) for s in sources] + ["-o", str(out)]
            command(args, label + "-" + target + "-build")
            save(f"build-{label}-{target}.json", {"command": args, "sha256": common.sha(out),
                "source_sha256": {s.name: common.sha(s) for s in sources},
                "head_sha256": common.sha(ROOT / "stage1_head.hpp") if label == "variant" else None})
            print("Built", label, target, flush=True)
        args = meta["compiler"] + base + ["-S", str(source / "nnue.cpp"), "-o", str(ART / (label + ".s"))]
        command(args, label + "-assembly")


def player(label: str, kernel: str | None = None):
    instance = open_engine(ART / label / "engine.exe")
    options = common.load(ROOT / "plan.json")["options"]
    instance.configure(dict(options, NNUEKernel=kernel or ("clip" if label == "variant" else "scalar")))
    return instance


def correctness() -> None:
    pin()
    data = {}
    for label, kernel in (("baseline", "scalar"), ("variant", "clip")):
        result = command([str(ART / label / "oracle.exe"), "--verify-throughput", kernel], label + "-transitions", 120)
        data[label + "_transition_oracle"] = json.loads(result)
        assert data[label + "_transition_oracle"] == {"bitwise_exact": True, "transitions": 31876, "nulls": 26908}
    data["head_parity"] = json.loads(command([str(ART / "variant/micro.exe"), "--parity", str(ROOT / "golden-fens.txt")], "head-parity", 120))
    assert data["head_parity"]["passed"]
    fixed = []
    with ExitStack() as stack:
        players = {label: stack.enter_context(player(label)) for label in ("baseline", "variant")}
        players["fallback"] = stack.enter_context(player("variant", "scalar"))
        players["frozen"] = stack.enter_context(open_engine(PROFILE / "artifacts/release/engine.exe"))
        players["frozen"].configure(common.load(ROOT / "plan.json")["options"])
        for row in common.load(ROOT / "positions.json"):
            for mode, budget in (("depth", 5), ("nodes", 200000)):
                records = {label: capture(instance, row, mode, budget) for label, instance in players.items()}
                assert all(canonical(r) == canonical(records["frozen"]) for r in records.values()), (row["id"], mode)
                fixed.append({"position": row["id"], "mode": mode, "records": records})
            print("Exact search parity", row["id"], flush=True)
    data["fixed_work"] = fixed
    data["passed"] = True
    save("correctness.json", data)


def micro() -> None:
    assert common.load(ROOT / "correctness.json")["passed"]
    assert common.load(ROOT / "regressions.json")["passed"]
    pin()
    data = {"records": [], "fen_records": [], "iterations_per_batch": 200000, "warmup": 10000}
    for repeat in range(7):
        for size in (1, 32, 128, 512):
            labels = ("baseline", "variant") if (repeat + size) % 2 else ("variant", "baseline")
            for label in labels:
                kernel = "clip" if label == "variant" else "scalar"
                raw = command([str(ART / label / "micro.exe"), "--bench", kernel, str(size), "200000"], f"{label}-micro-{repeat}-{size}")
                data["records"].append(dict(json.loads(raw), build=label, repeat=repeat, frames=size))
        for i, row in enumerate(common.load(ROOT / "positions.json")):
            for label in (("baseline", "variant") if (repeat+i) % 2 else ("variant", "baseline")):
                kernel = "clip" if label == "variant" else "scalar"
                raw = command([str(ART / label / "micro.exe"), "--fen", kernel, row["fen"], "200000"], f"{label}-fen-{repeat}-{row['id']}")
                data["fen_records"].append(dict(json.loads(raw), build=label, repeat=repeat, position=row["id"]))
        save("micro.json", data)
        print("Paired micro pass", repeat + 1, flush=True)


def search() -> None:
    assert common.load(ROOT / "correctness.json")["passed"]
    assert common.load(ROOT / "regressions.json")["passed"]
    pin()
    path = ROOT / "search.json"
    data = common.load(path) if path.exists() else {"records": [], "environment_segments": []}
    done = {(r["position"], r["mode"], r["budget"], r["build"], r["repeat"]) for r in data["records"]}
    plan = common.load(ROOT / "plan.json")
    with ExitStack() as stack:
        players = {label: stack.enter_context(player(label)) for label in ("baseline", "variant")}
        from load_meter import Meter
        meter = Meter([os.getpid()] + [instance.transport.get_pid() for instance in players.values()])
        stack.callback(meter.close)
        for instance in players.values():
            capture(instance, common.load(ROOT / "positions.json")[0], "nodes", 50000)
        for repeat in range(plan["repeats"]):
            for i, row in enumerate(common.load(ROOT / "positions.json")):
                for mode, budget in plan["budgets"]:
                    labels = ("baseline", "variant") if (repeat+i) % 2 else ("variant", "baseline")
                    for label in labels:
                        if (row["id"], mode, budget, label, repeat) in done:
                            continue
                        record = capture(players[label], row, mode, budget)
                        assert record["counters"]["nnue_evaluations"] == record["counters"]["eval_calls"]
                        data["records"].append(dict(record, build=label, repeat=repeat))
                    if mode == "nodes":
                        pair = [r for r in data["records"] if r["position"] == row["id"] and r["mode"] == mode and r["budget"] == budget and r["repeat"] == repeat]
                        assert len(pair) == 2 and canonical(pair[0]) == canonical(pair[1]), row["id"]
                    save("search.json", data)
                data["environment_segments"].append(dict(meter.read(), repeat=repeat, position=row["id"]))
                save("search.json", data)
                print("Paired search pass", repeat+1, row["id"], flush=True)


def preserve() -> None:
    protected = common.load(ROOT / "preservation-before.json")
    changed = [name for name, sha in protected.items() if common.sha(REPO / name) != sha]
    save("preservation-after.json", {"checked_files": len(protected), "changed": changed, "passed": not changed})
    assert not changed, changed


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "build", "correctness", "micro", "search", "preserve"))
    globals()[parser.parse_args().action]()
