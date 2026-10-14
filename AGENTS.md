Whatever action you can do yourself, Please do yourself, this includes starting apps and verification

You have full authorization to commit and push repository changes. Push to the configured remote; if blocked, commit locally and report the commit so the user can push manually. Commit the initial README before application implementation.

# Repository Guidelines

## Project structure and module organization

ChessLab is a Python/Pygame application for engine development.

- `app/`: Python application; separate startup, game state, board rendering, input handling, and `ui/` components.
- `app/assets/`: bundled piece images and attribution/license notices.
- `tests/`: automated game-state, input, and rendering tests.
- `engine/src/`: C++17 UCI protocol and Minimax/alpha-beta search.
- `engine/vendor/`: pinned MIT-licensed rules library; keep upstream files unchanged.
- `tools/prepare_assets.py`: development-only artwork conversion; `--offline` uses local SVGs.

## Build, test, and development commands

Target Python 3.11+. From the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m app.main
.\.venv\Scripts\python.exe -m pytest
```

Windows: run `setup.bat`, `build_engine.bat`, then `launch.bat`. Build before running the full suite. Linux: use `.venv/bin/python tools/build_engine.py` with C++17 or pinned build requirements. Set `CXX` to override the compiler.

## Coding style and naming conventions

Use four spaces, PEP 8, `snake_case` functions, `PascalCase` classes, and `UPPER_CASE` constants. Type public interfaces. No formatter is configured.

Keep game logic independent of Pygame; validate moves with `python-chess`. Use package-relative assets and responsive events.

C++: use four spaces and `snake_case`; separate protocol/search. Algorithms share evaluation, limits, and ordering.

## Testing guidelines

Use pytest with `test_*.py` files and `test_<behavior>` functions. Cover rules, perft, search equivalence, UCI cancellation, stale replies, and GUI interactions. Tests use SDL's dummy driver. Inspect frames and launch the app; distinguish automated and desktop checks. Never claim unverified behavior works.

## Commit and pull request guidelines

Use imperative subjects, such as `Add promotion selection dialog`. Keep commits focused. PRs need behavior changes, validation, limitations, relevant issues, and screenshots for visual changes.

## Development boundaries

Gameplay defaults to timed deepening. Aspiration/NMP/LMR are switchable; Minimax ignores them. Disable advanced features for exhaustive baselines. Preserve exact aspiration retries, isolated null histories/cache, LMR verification, draw context, TT bounds, fallbacks, board restoration, and completed snapshots. Never claim selective scores equal exhaustive results. Defer killer/history heuristics and further pruning until requested. Keep UCI off the GUI thread, reject stale replies, and play only final validated moves. Preserve complete pawn-cache keys and live occupancy-dependent terms. Preserve attribution.
