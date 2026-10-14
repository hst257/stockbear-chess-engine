"""Build the standalone C++17 engine without requiring CMake.

Use CXX to select a compiler executable, or install engine/requirements-build.txt
for the project-local Zig C++ driver. No compiler is needed at engine runtime.
"""

import importlib.util
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=("engine", "tt-tests"), default="engine")
    target = parser.parse_args().target
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
    name = "chesslab-engine" if target == "engine" else "chesslab-tt-tests"
    output = ROOT / "engine" / "build" / (name + (".exe" if os.name == "nt" else ""))
    output.parent.mkdir(parents=True, exist_ok=True)
    args = compiler + ["-std=c++17", "-O2", "-pthread", "-Wall", "-Wextra",
                       "-I", str(ROOT / "engine" / "vendor" / "chess-library"),
                       "-I", str(ROOT / "engine" / "src"),
                       str(ROOT / "engine" / ("src/main.cpp" if target == "engine" else "tests/test_transposition.cpp")),
                       str(ROOT / "engine" / "src" / "search.cpp"),
                       str(ROOT / "engine" / "src" / "evaluation.cpp"), "-o", str(output)]
    print("Building with " + " ".join(compiler), flush=True)
    environment = os.environ.copy()
    environment.setdefault("ZIG_GLOBAL_CACHE_DIR", str(output.parent / "zig-cache"))
    environment.setdefault("ZIG_LOCAL_CACHE_DIR", str(output.parent / "zig-local-cache"))
    result = subprocess.run(args, cwd=ROOT, env=environment, check=False)
    if result.returncode:
        print("Build failed. Try the pinned compiler in engine/requirements-build.txt.", file=sys.stderr)
    else:
        print(f"Built {output}")
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
