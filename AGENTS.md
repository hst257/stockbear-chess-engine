Whatever action you can do yourself, Please do yourself, this includes starting apps and verification

You have full authorization to commit and push repository changes. Make focused commits and push to the configured remote when available. If pushing is blocked, commit locally and report the commit so the user can push manually. Create the initial README and first commit before starting application implementation.

# Repository Guidelines

## Project structure and module organization

ChessLab is a Python/Pygame desktop chess application for learning engine development.

- `app/`: Python application; separate startup, game state, board rendering, input handling, and `ui/` components.
- `app/assets/`: locally bundled piece images and attribution/license notices.
- `tests/`: automated game-state, input, and rendering tests.
- `engine/README.md`: future C++/UCI documentation only.
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

These create an environment, install dependencies, launch, and test. Windows shortcuts: `setup.bat` then `launch.bat`. Linux: `.venv/bin/python`. No compilation is required.

## Coding style and naming conventions

Use four-space indentation, PEP 8, `snake_case` modules/functions, `PascalCase` classes, and `UPPER_CASE` constants. Add public-interface type hints. Keep functions focused. No formatter or linter is configured.

Keep game logic independent of Pygame. Use `python-chess` for legal moves and outcomes; validate moves before pushing them. Resolve assets with package-relative paths and keep the event loop responsive.

## Testing guidelines

Use pytest with `test_*.py` files and `test_<behavior>` functions. Cover special moves, illegal moves, outcomes, draw claims, undo/reset, and both orientations. Tests set SDL's dummy video driver. No numerical coverage threshold is set. Inspect rendered frames and launch the app yourself; report automated and desktop checks separately. Never claim unverified behavior works.

## Commit and pull request guidelines

Use concise imperative subjects, such as `Add promotion selection dialog`. Keep changes focused. PRs should explain behavior changes, validation results, and limitations; link relevant issues and include screenshots for visual changes.

## Development boundaries

Implement Phase 1 local Human vs Human only. Defer AI opponents, C++ engine code, and later search techniques until explicitly requested. Avoid future-phase placeholders, web services, databases, and machine-learning dependencies. Document eventual standalone UCI integration without implementing it. Preserve local asset attribution and keep README claims aligned with tested features.
