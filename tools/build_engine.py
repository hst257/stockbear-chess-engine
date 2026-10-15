"""Build the standalone C++17 engine without requiring CMake.

Use CXX to select a compiler executable, or install engine/requirements-build.txt
for the project-local Zig C++ driver. No compiler is needed at engine runtime.
"""

import json
import importlib.util
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.embed_nnue import DEFAULT_MODEL, generate_header


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=("engine", "tt-tests", "audit-tests"), default="engine")
    parser.add_argument("--profile", action="store_true", help="Instrument CPU categories and search-thread allocations.")
    parser.add_argument("--optimization", choices=("O2", "O3"), default="O2")
    parser.add_argument("--lto", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--nnue-model", type=Path, default=DEFAULT_MODEL,
                        help="Validate and embed a custom StockBear float32 v1 export.")
    parser.add_argument("--sanitize", choices=("undefined",), help="Development-only undefined-behavior checks.")
    options = parser.parse_args()
    target = options.target
    if os.environ.get("CXX"):
        compiler = [os.environ["CXX"]]
    elif importlib.util.find_spec("ziglang"):
        compiler = [sys.executable, "-m", "ziglang", "c++"]
    else:
        found = shutil.which("clang++") or shutil.which("g++")
        if not found:
            print("Install engine/requirements-build.txt or set CXX to a C++17 compiler.", file=sys.stderr)
            return 1
        compiler = [found]
    name = "chesslab-" + ("engine" if target == "engine" else target)
    output = options.output or ROOT / "engine" / "build" / (name + (".exe" if os.name == "nt" else ""))
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    generated = output.parent / "generated"
    try:
        model_info = generate_header(options.nnue_model.resolve(), generated / "nnue_weights.hpp")
    except (ValueError, KeyError, OSError) as error:
        print(f"NNUE model validation failed: {error}", file=sys.stderr)
        return 1
    args = compiler + ["-std=c++17", "-" + options.optimization, "-pthread", "-Wall", "-Wextra", "-ffp-contract=off",
                       "-I", str(generated),
                       "-I", str(ROOT / "engine" / "vendor" / "chess-library"),
                       "-I", str(ROOT / "engine" / "src"),
                       str(ROOT / "engine" / ("src/main.cpp" if target == "engine" else
                           "tests/test_transposition.cpp" if target == "tt-tests" else "tests/test_audit.cpp")),
                       str(ROOT / "engine" / "src" / "search.cpp"),
                       str(ROOT / "engine" / "src" / "evaluation.cpp"),
                       str(ROOT / "engine" / "src" / "nnue.cpp"), "-o", str(output)]
    if options.profile:
        args.insert(len(compiler), "-DCHESSLAB_PROFILE")
    if options.lto:
        args.insert(len(compiler), "-flto")
    if options.sanitize:
        args[len(compiler):len(compiler)] = ["-fsanitize=" + options.sanitize, "-fno-sanitize-recover=all"]
    print("Building with " + " ".join(compiler), flush=True)
    environment = os.environ.copy()
    environment.setdefault("ZIG_GLOBAL_CACHE_DIR", str(output.parent / "zig-cache"))
    environment.setdefault("ZIG_LOCAL_CACHE_DIR", str(output.parent / "zig-local-cache"))
    result = subprocess.run(args, cwd=ROOT, env=environment, check=False)
    if result.returncode:
        print("Build failed. Try the pinned compiler in engine/requirements-build.txt.", file=sys.stderr)
    else:
        print(f"Built {output}")
        output.with_suffix(".build.json").write_text(json.dumps({
            "compiler": compiler, "flags": args[len(compiler):], "profile": options.profile,
            "optimization": options.optimization, "lto": options.lto, "sanitizer": options.sanitize,
            "nnue": model_info,
        }, indent=2) + "\n", encoding="utf-8")
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
