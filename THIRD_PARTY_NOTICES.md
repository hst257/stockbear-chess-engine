# Third-party notices

ChessLab installs these dependencies through pip; their source and licenses remain
with their respective projects and installed distributions:

| Component | Version | License | Source |
| --- | --- | --- | --- |
| Pygame | 2.6.1 | GNU LGPL (see upstream terms) | https://github.com/pygame/pygame |
| python-chess package | 1.999 | GNU GPL 3 or later | https://github.com/niklasf/python-chess |
| chess library | 1.11.2 | GNU GPL 3 or later | https://github.com/niklasf/python-chess |
| pytest (development only) | 8.4.2 | MIT | https://github.com/pytest-dev/pytest |
| chess-library (vendored C++ rules) | 0.9.4 | MIT | https://github.com/Disservin/chess-library |
| Zig compiler (build only) | 0.13.0 | MIT for Zig; bundled components retain upstream terms | https://ziglang.org/ |

python-chess is the package that depends on the `chess` library. Both are pinned
to make the tested runtime explicit. Transitive dependency notices are available
in `.venv/Lib/site-packages/` on Windows or the equivalent environment directory
on Linux. The virtual environment is not committed or distributed with this repo.

The bundled Cburnett piece images have separate CC BY-SA 3.0 terms. Their sources,
authors, conversion details, and full license are recorded in
[app/assets/ATTRIBUTION.md](app/assets/ATTRIBUTION.md).

The C++ library's pinned source and full license are retained in
[engine/vendor/chess-library](engine/vendor/chess-library/README.md). It provides
rules only; ChessLab implements search/evaluation. Zig is installed in the ignored
virtual environment; bundled LLVM/libc++/runtime notices remain with its distribution.
