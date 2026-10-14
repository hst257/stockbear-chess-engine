# ChessLab

ChessLab is a desktop chess application and a project for learning chess-engine search algorithms step by step. The first milestone is a complete local two-player game. A custom standalone C++ engine will follow in later phases.

## Current status

The repository currently contains project documentation and contributor instructions. Application code, dependency files, launch scripts, and tests have not been implemented yet. There is no playable release or runnable application at this stage.

## Technology

- Python 3.11+ for the desktop application.
- Pygame for rendering and mouse interaction.
- python-chess for board representation, legal moves, and rules.
- Windows as the primary development platform, with Linux compatibility in mind.
- C++17 or C++20 and UCI for the future standalone engine.

## Phase 1: local two-player chess

The planned application includes:

- A dark slate interface with ivory and walnut board squares, locally bundled licensed pieces, and rank/file coordinates.
- Click-to-select and click-to-move controls, legal destinations, previous-move highlights, and check indicators.
- Castling, en passant, promotion selection, checkmate, stalemate, automatic draws, and explicit repetition/fifty-move draw claims.
- A sidebar showing turn, game status, captured pieces, and standard algebraic move history.
- New Game, Undo Move, and manual Flip Board controls.
- Automated rules/state tests and separate interface verification.

These are planned features, not implemented capabilities. Phase 1 will have no AI opponent.

## Planned organization

```text
app/                  Application startup, state, rendering, and input
  ui/                 Sidebar and dialogs
  assets/             Local piece images and attribution
tests/                Game-state and interface tests
engine/README.md      Future engine integration notes
requirements.txt      Runtime dependencies
requirements-dev.txt  Test dependencies
```

Only the root documentation and ignore rules exist initially. Keep game state independent of Pygame so rendering and input can be tested separately.

## Installation and launch

Python 3.11+ is required for the planned application. Installation and launch instructions will be added after dependency files and the application entry point exist and have been verified. Windows setup and launch scripts will use a project-local virtual environment; equivalent Linux commands will also be documented.

## Development and verification

Read [AGENTS.md](AGENTS.md) for contributor instructions. Future tests will use pytest and cover normal play, special moves, draw claims, undo/reset, and board orientation. No automated tests or application launch checks are available yet.

Piece assets will be bundled locally with their source and license notices before release. The application will not require network access at runtime.

## Roadmap

1. Complete the playable Python/Pygame local two-player application.
2. Add a basic independent C++ UCI engine with material evaluation and depth-limited Minimax or Negamax.
3. Add switchable alpha-beta pruning and compare nodes, depth, time, and selected moves using identical evaluation/depth settings.
4. Introduce iterative deepening, move ordering, transposition tables, quiescence search, and Principal Variation Search individually.
5. Explore advanced pruning and evaluation only after the fundamentals are reliable.
6. Add engine matches and performance/strength benchmarks.

Later phases require an explicit request. The custom engine will perform its own search and evaluation rather than delegate them to another engine.

## Future engine integration

The Python application will launch the engine as a separate UCI subprocess through python-chess. Engine communication will run without blocking the GUI, and returned moves will pass through the same legality validation as human moves. The C++ executable will represent positions and generate legal moves independently of the GUI.
