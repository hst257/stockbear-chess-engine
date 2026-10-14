Whatever action you can do yourself, Please do yourself, this includes starting apps and verification

You have full authorization to commit and push repository changes. Push to the configured remote; if blocked, commit locally and report the commit so the user can push manually. Commit the initial README before application implementation.

# Repository Guidelines

## Project structure and module organization

ChessLab is a Python/Pygame desktop chess application for learning engine development.

- `app/`: Python application; separate startup, game state, board rendering, input handling, and `ui/` components.
- `app/assets/`: locally bundled piece images and attribution/license notices.
- `tests/`: automated game-state, input, and rendering tests.
- `engine/src/`: standalone C++17 UCI protocol and Minimax/alpha-beta search.
- `engine/vendor/`: pinned MIT-licensed rules library; keep upstream files unchanged.
- `tools/prepare_assets.py`: development-only artwork conversion; `--offline` uses local SVGs.

## Build, test, and development commands

Target Python 3.11+. Run from the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m app.main
.\.venv\Scripts\python.exe -m pytest
```

Windows: run `setup.bat`, `build_engine.bat`, then `launch.bat`. Build before running the full suite. Linux: use `.venv/bin/python tools/build_engine.py` with a C++17 compiler or the pinned build requirements. Set `CXX` to override the compiler.

## Coding style and naming conventions

Use four spaces, PEP 8, `snake_case` functions, `PascalCase` classes, and `UPPER_CASE` constants. Type public interfaces. No formatter is configured.

Keep Python game logic independent of Pygame; validate with `python-chess` before pushing moves. Use package-relative assets and a responsive event loop.

Use four spaces and `snake_case` functions in C++; keep protocol and search separate. Both algorithms must share evaluation, depth, and move order.

## Testing guidelines

Use pytest with `test_*.py` files and `test_<behavior>` functions. Cover rules, perft, search equivalence, UCI cancellation, stale replies, and GUI interactions. Tests use SDL's dummy driver. Inspect frames and launch the app; distinguish automated and desktop checks. Never claim unverified behavior works.

## Commit and pull request guidelines

Use imperative subjects, such as `Add promotion selection dialog`. Keep commits focused. PRs need behavior changes, validation, limitations, relevant issues, and screenshots for visual changes.

## Development boundaries

The current milestone combines Phases 2 and 3: C++ engine, Human vs Engine, Minimax, alpha-beta, and diagnostics. Defer modern search until requested. Keep search/evaluation our own; do not delegate to another engine. Run UCI work off the GUI thread and discard stale results. Preserve attribution and keep README claims aligned with tested features.
