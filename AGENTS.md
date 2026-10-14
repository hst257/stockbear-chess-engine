Whatever action you can do yourself, Please do yourself, this includes starting apps and verification

You have full authorization to commit and push repository changes. Make focused commits and push to the configured remote when available. If pushing is blocked, commit locally and report the commit so the user can push manually. Create the initial README and first commit before starting application implementation.

# Repository Guidelines

## Project structure and module organization

ChessLab is a desktop chess application for learning engine development. Application implementation has not started. Use the following planned layout when implementing Phase 1:

- `app/`: Python application; separate startup, game state, board rendering, input handling, and `ui/` components.
- `app/assets/`: locally bundled piece images and attribution/license notices.
- `tests/`: automated game-state, input, and rendering tests.
- `engine/README.md`: future C++/UCI architecture documentation only.
- Root: dependency files, Windows setup/launch scripts, README, and `.gitignore`.

## Build, test, and development commands

Target Python 3.11+. Once the application and dependency files exist, run these commands from the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m app.main
.\.venv\Scripts\python.exe -m pytest
```

These create an isolated environment, install runtime/test dependencies, launch the game, and run tests. On Linux, use `.venv/bin/python`. Phase 1 requires no compilation step.

## Coding style and naming conventions

Use four-space indentation, PEP 8 conventions, `snake_case` modules/functions, `PascalCase` classes, and `UPPER_CASE` constants. Add type hints to public interfaces. Keep functions focused and explain architectural decisions in comments where useful. No formatter or linter is configured yet.

Keep game logic independent of Pygame. Use `python-chess` for legal moves and outcomes; validate moves before pushing them. Resolve assets with package-relative paths and keep the event loop responsive.

## Testing guidelines

Use pytest with `test_*.py` files and `test_<behavior>` functions. Cover captures, illegal moves, castling, en passant, promotion, terminal positions, draw claims, undo/reset, and both board orientations. Use SDL's dummy video driver for headless rendering tests. No numerical coverage threshold is set. Report automated results and manual UI checks separately; never claim unverified behavior works.

## Commit and pull request guidelines

Use concise imperative subjects, such as `Add promotion selection dialog`. Keep changes focused. PRs should explain behavior changes, validation results, and limitations; link relevant issues and include screenshots for visual changes.

## Development boundaries

Implement Phase 1 local Human vs Human only. Defer AI opponents, C++ engine code, and later search techniques until explicitly requested. Avoid future-phase placeholders, web services, databases, and machine-learning dependencies. Document eventual standalone UCI integration without implementing it. Preserve local asset attribution and keep README claims aligned with tested features.
