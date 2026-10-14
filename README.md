# ChessLab

ChessLab is a local two-player desktop chess game and a project for learning chess-engine search algorithms step by step. Phase 1 uses Python, Pygame, and python-chess. A custom standalone C++ engine belongs to a later phase.

![ChessLab's local two-player board](docs/chesslab.png)

## Install and play on Windows

Install **Python 3.11 or newer** with Python on PATH. The verified environment is Windows with Python 3.11.8 and Pygame 2.6.1. Open PowerShell in this folder and run:

```powershell
.\setup.bat
.\launch.bat
```

Setup creates `.venv` and installs the pinned dependencies. It requires internet access on the first installation. The game uses bundled assets and needs no network connection. You can also double-click `launch.bat` after setup.

For manual installation or development:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m app.main
```

The launch script changes to its own folder, so it works regardless of your current working directory. Direct module commands should run from the repository root. Missing assets or dependencies produce an error with setup instructions.

### Linux

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m app.main
```

Linux commands are provided for portability but have not been run on a Linux desktop. A graphical session is required for normal play.

## Controls

| Action | Mouse | Keyboard |
| --- | --- | --- |
| Move | Click your piece, then a legal destination | — |
| Change selection | Click another friendly piece | — |
| Deselect/cancel dialog | Click outside the board / dialog's Cancel | Escape |
| New game | New game | N |
| Undo one move | Undo move | U |
| Reverse orientation | Flip board | F |
| Claim an eligible draw | Claim draw | D |
| Choose promotion | Click Queen, Rook, Bishop, or Knight | Q, R, B, N in the promotion dialog |
| Scroll move history | Mouse wheel over the history | — |

White starts at the bottom; the board stays put between turns. New Game immediately resets the position, history, selection, and orientation. Undo removes one half-move; after a claimed draw, the first Undo withdraws the claim and leaves the board unchanged.

## Implemented features

- Resizable dark slate interface, ivory/walnut board, rank/file labels, and licensed local chess-piece artwork.
- Piece selection, legal destination dots, capture rings, previous-move highlights, and a checked-king indicator.
- Legal standard chess moves, captures, both castling sides, en passant, and all four promotion choices.
- Current turn, captured pieces grouped by capturing player, scrolling SAN move history, and clear results identifying the winner or draw reason.
- Checkmate, stalemate, insufficient material, automatic fivefold repetition, and the seventy-five-move rule.
- Explicit threefold repetition and fifty-move claims. The claim dialog lists eligible current-position claims or intended moves; scroll for additional choices. An intended-move claim declares the move without playing it.
- Reversible game endings, Undo, restart, manual board flipping, and keyboard shortcuts.

## Architecture

```text
app/
  main.py             CLI, startup errors, and shutdown
  application.py      Pygame event loop and layout
  game.py             Validated moves, history, captures, outcomes, draw claims
  input_handler.py    Selection and pending promotion
  board_renderer.py   Orientation mapping, board drawing, cached piece images
  ui/                 Shared style, sidebar, promotion and claim dialogs
  assets/             PNG pieces, original SVGs, and license/attribution
tests/                Rules, interaction, event-loop, and rendering tests
tools/prepare_assets.py  Development-only artwork conversion
engine/README.md      Future UCI integration notes; no engine implementation
```

`Game` has no Pygame dependency. It validates a move before changing the board and records SAN and the actual captured piece before pushing. This also handles en passant and captures of promoted pieces correctly. Undo uses the original board stack, preserving castling, en passant, and repetition history.

`InputHandler` keeps temporary selection and promotion separate from committed moves. Rendering reads the game state. Board coordinates and hit testing share one orientation transform. Expensive draw eligibility checks are cached after state changes; fonts and piece images are cached, and the event loop runs at up to 60 FPS.

## Tests and verification

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pip check
.\launch.bat --smoke-test 3 --screenshot chesslab.png
```

**Verified on Windows: 71 automated tests pass.** Coverage includes normal play/captures, illegal moves, pins, castling and attacked-square rejection, en passant, all promotions, terminal positions, current/intended draw claims, automatic draws, checkmate precedence, and a seeded 180-half-move game rewound position by position.

Headless Pygame tests exercise mouse/keyboard events, modal dialogs, scrolling, resize, both orientations, artwork dimensions, missing-asset errors, and event-loop shutdown. Tests set SDL's dummy video driver so they do not open desktop windows. Screenshots of the initial board, promotion, checkmate, and draw dialog were visually inspected.

Windows setup, launch-script smoke testing, dependency consistency checks, and actual desktop-window launch/display inspection passed. Native mouse automation was interrupted by desktop input; mouse interactions are verified through the automated Pygame event tests, not claimed as a completed native mouse walkthrough.

Read [AGENTS.md](AGENTS.md) for contributor instructions.

## Assets and dependencies

The Cburnett chess pieces and PNG conversions use CC BY-SA 3.0. All twelve individual source pages were checked for that license offer. See [asset attribution](app/assets/ATTRIBUTION.md) and the bundled full license. Runtime loads only the checked-in PNGs.

Rebuild the PNGs from local SVGs, without downloads:

```powershell
.\.venv\Scripts\python.exe tools\prepare_assets.py --offline
```

Running that tool without `--offline` checks the source licenses online and downloads missing originals. Third-party library notices are in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## Current limitations

- Local Human vs Human only; no AI, engine analysis, clocks, save/load, PGN export, or drag movement.
- Games are held in memory and are discarded when the application closes.
- The minimum supported layout is 960 × 680; text uses an available system font.
- Dead-position adjudication follows python-chess's insufficient-material detection. Unusual blocked positions that are dead for other reasons are not exhaustively detected.
- Linux desktop behavior and other Python versions have not been verified.

## Roadmap

1. **Implemented:** playable Python/Pygame local two-player application.
2. Add a basic independent C++ UCI engine with material evaluation and depth-limited Minimax or Negamax.
3. Add switchable alpha-beta pruning and compare nodes, depth, time, and selected moves using identical evaluation/depth settings.
4. Introduce iterative deepening, move ordering, transposition tables, quiescence search, and Principal Variation Search individually.
5. Explore advanced pruning and evaluation only after the fundamentals are reliable.
6. Add engine matches and performance/strength benchmarks.

Later phases require an explicit request. The custom engine will perform its own search and evaluation rather than delegate them to another engine.

## Future engine integration

The Python application will launch the engine as a separate UCI subprocess through python-chess. Engine communication will run without blocking the GUI, and returned moves will pass through the same legality validation as human moves. The C++ executable will represent positions and generate legal moves independently of the GUI.

The adapter will search a board copy and retain `Game.revision`; results from an outdated position will be discarded after Undo or New Game. See [engine integration notes](engine/README.md). No engine code is included in Phase 1.
