"""Check sanitizer compiler/runtime availability with an engine-independent probe."""
from pathlib import Path
import subprocess
import sys

from tools.nnue_throughput import ART, ROOT, save


def main():
    folder = ART / "asan-probe"
    folder.mkdir(parents=True, exist_ok=True)
    source = folder / "probe.cpp"
    source.write_text('#include <stdexcept>\n#include <vector>\nint main(int argc, char**) {\n'
                      'try { if (argc) throw std::invalid_argument("probe"); } catch (const std::exception&) {}\n'
                      'try { std::vector<int> values; return values.at(argc); } catch (const std::out_of_range&) { return 0; }\n}\n')
    records = []
    for name, compiler in (("zig", [sys.executable, "-m", "ziglang", "c++"]),
                           ("mingw", ["C:/MinGW/bin/g++.exe"])):
        executable = folder / (name + ".exe")
        result = subprocess.run(compiler + ["-std=c++17", "-O2", "-fsanitize=address", str(source), "-o", str(executable)],
                                capture_output=True, text=True)
        row = {"compiler": compiler, "build_exit": result.returncode, "build_log": result.stdout + result.stderr}
        if result.returncode == 0:
            execution = subprocess.run([str(executable.resolve())], capture_output=True, text=True)
            row.update(run_exit=execution.returncode, run_log=execution.stdout + execution.stderr)
        records.append(row)
    save(ROOT / "asan-probes.json", {"engine_independent_standard_library_probe": True, "probes": records})
    print(records)


if __name__ == "__main__":
    main()
