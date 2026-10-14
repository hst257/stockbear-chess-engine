# ChessLab engine: combined Phases 2 and 3

A standalone C++17 UCI executable implements material-only Minimax with optional
alpha-beta pruning. It owns its board and generates moves independently of Python.
No search or evaluation is delegated to another engine.

## Build

From the repository root on Windows:

```powershell
.\setup.bat
.\build_engine.bat
.\launch.bat --mode engine
```

The build script installs the pinned Zig 0.13.0 C++ compiler into `.venv` and builds
`engine/build/chesslab-engine.exe`. No global compiler installation or CMake is
needed. The initial compiler download is about 80 MB; it is not a runtime dependency.
Generated binaries and compiler caches are ignored by Git.

On Linux, use `.venv/bin/python tools/build_engine.py` with recent C++17 GCC/Clang,
or install `engine/requirements-build.txt` for the pinned compiler. Set `CXX` to a
compiler executable to override detection. Output is `engine/build/chesslab-engine`.
Linux builds have not been verified in this Windows development environment.

## Shared search and evaluation

`src/search.cpp` contains one recursive Minimax implementation. White maximizes
and Black minimizes the same material score:

| Piece | Centipawns |
| --- | ---: |
| Pawn | 100 |
| Knight | 320 |
| Bishop | 330 |
| Rook | 500 |
| Queen | 900 |
| King | 0 (handled through terminal detection) |

Each node generates legal moves, checks mate/stalemate, checks draws, then
evaluates material at depth zero. Mate distance favors faster wins and slower
losses. Terminal detection precedes draw counters.

With `AlphaBeta=false`, every branch is searched. With `AlphaBeta=true`, the same
function updates alpha/beta bounds and cuts branches that cannot affect the answer.
Both modes retain identical move traversal and a first-best tie rule. No iterative
deepening, heuristic sorting, transposition table, quiescence, positional evaluation,
opening book, or neural network is implemented.

Depth counts plies (half-moves). Nodes include root, interior, terminal, and static
leaves. Time uses a monotonic clock in milliseconds; tiny searches can report zero.

Search treats currently claimable threefold/50-move positions as drawn. The GUI
automatically claims eligible draws on the engine's turn, including intended-move
claims, before requesting a move. It may claim even when a win could exist. Human
claims remain explicit.

## UCI

Run the executable directly and enter one command per line:

```text
uci
isready
setoption name AlphaBeta value true
position startpos moves e2e4 e7e5
go depth 3
```

Commands: `uci`, `isready`, `ucinewgame`, `setoption`, `position startpos`,
`position fen` (six fields, optionally followed by moves), `go`, `stop`, `quit`.
Options: `AlphaBeta` (default true), `Depth` (default 3, range 1–8).
`go` accepts depth, movetime (milliseconds), nodes, and infinite. Without explicit
depth it uses the Depth option. Clock allocation and pondering are not implemented.
Timed searches do not use iterative deepening.

The input thread remains responsive during worker searches. `info` reports depth,
selective depth, nodes, time, approximate NPS, score, and legal principal variation.
UCI scores favor the player to move; the GUI converts to White's perspective.
Terminal/no-move results use `bestmove 0000`.

Interrupted searches return a provisional legal move, report depth zero, and omit
an unproven score. The GUI uses a 15-second safety limit per search, allows depths
1–5, and labels partial results instead of comparing them as completed searches.
Unknown commands are ignored; invalid positions/moves report errors and leave
the previous position unchanged.

## GUI integration

Press G for opponent/color/algorithm/depth settings and E for Search lab. Compare
position runs both algorithms sequentially on one snapshot without playing either
move. It displays move, completed depth, nodes, time, score, and node reduction.
Play pauses while this panel is open.

`app/engine_client.py` communicates through python-chess in a background worker.
Jobs receive full-history board copies and revision/tokens. Only the GUI thread
applies validated replies through `Game.play`. Reset, Undo, mode changes, and
shutdown cancel subprocess work; stale replies are ignored. Errors leave the game
unchanged instead of triggering a retry loop.

## Verification

Build first, then run `.venv\Scripts\python.exe -m pytest -q` from the root.
Tests include perft (197,281 at initial depth 4; 97,862 at Kiwipete depth 3), legal
move cross-checks against python-chess, terminal states, search equivalence,
interruptible UCI, cancellation, and actual engine-to-GUI play/comparison.

Initial position, depth 3, this build:

| Algorithm | Best move | Score (White) | Nodes |
| --- | --- | ---: | ---: |
| Minimax | a3 | 0.00 | 9,323 |
| Alpha-beta | a3 | 0.00 | 586 |

Alpha-beta visits 93.7% fewer nodes with the same answer. This measures work, not
playing strength: material-only evaluation makes many quiet moves equivalent.

Standalone rules diagnostics:

```powershell
.\engine\build\chesslab-engine.exe --perft 4
.\engine\build\chesslab-engine.exe --legal-moves "7k/P7/8/8/8/8/8/7K w - - 0 1"
```

## Third-party rules

Disservin's MIT-licensed C++ chess library version 0.9.4 is vendored at revision
`53e6a841dcda7059a2af363d85f785ef1817304a`. The original header/license are unchanged.
Its position hashes support repetition detection; ChessLab has no search cache.
