# ChessLab engine: Minimax, alpha-beta, deepening, and ordering

A standalone C++17 UCI executable implements material-only Minimax with optional
alpha-beta pruning, switchable iterative deepening, and move ordering. It owns its board independently of Python.
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
Both modes share the same ordering policy and first-best tie rule. Transposition
tables, quiescence, killer/history heuristics, positional evaluation, opening books,
and neural networks are deferred.

## Iterative deepening

Enabled by default, deepening searches depth 1, then 2, through the target depth.
Each completed pass commits its move, score, and principal variation together and
emits a UCI `info` update. A deeper unfinished pass cannot overwrite that snapshot.
Time and node limits cover all passes together, not a fresh budget for each pass.

On `stop` or a limit, the engine returns the last completed result. Depth reports
that completed depth, while final nodes/time include work spent on the interrupted
pass. Before depth 1 finishes, it returns an unscored legal fallback at depth 0.
Terminal positions are resolved directly without repeating identical passes.

Toggle **Depth 1 → target / Target depth only** in game setup, or **Deepening: on/off**
in Search lab. The latter preserves the board. CLI: `--no-iterative-deepening`
selects the original direct search. UCI: `setoption name IterativeDeepening value false`.
Both comparison algorithms use the same deepening setting, depth, and evaluation.

Completed full-depth scores match direct search. With ordering enabled, the
previous PV can change which equally good move is searched first. Its benefit
depends on the position; shallow passes still count toward the total work.

Depth counts plies (half-moves). Nodes include root, interior, terminal, and static
leaves across all passes, including repeated positions and unfinished work. Completed
pass history records cumulative totals at each checkpoint. Time uses a monotonic
clock in milliseconds; tiny searches can report zero.

Search treats currently claimable threefold/50-move positions as drawn. The GUI
automatically claims eligible draws on the engine's turn, including intended-move
claims, before requesting a move. It may claim even when a win could exist. Human
claims remain explicit.

## Move ordering

Enabled by default in both algorithms. At each non-leaf node, stable sorting uses:

1. The previous completed iteration's PV move, only while following that PV's
   exact prefix. Siblings never reuse hints based only on their ply.
2. Promotions, prioritized by promoted-piece value and any capture bonus.
3. Captures using MVV-LVA: `10 × victim value − attacker value`.
4. Quiet moves in the original rules-library order.

The library identifies en passant's pawn victim and excludes castling from
captures. Capture promotions receive both bonuses. Equal priorities preserve
library order; the first equally scored searched move wins. Ordering can change
the selected move/PV among ties while preserving the full-depth minimax score.
It creates earlier alpha-beta cutoffs; exhaustive Minimax visits the same nodes
and pays sorting overhead. Node savings and elapsed-time gains vary by position.

Setup offers **PV / promotions / captures** and **Original move order**. Search
lab's **Ordering: on/off** preserves the board and clears old rows; rerun Compare
position to measure the new setting. Toggles are disabled during searches. CLI:
`--no-move-ordering`. UCI: `setoption name MoveOrdering value false`. Disabling
ordering bypasses all sorting and PV hints, restoring the original traversal.
Hints are local to one search and come only from fully completed passes.

## UCI

Run the executable directly and enter one command per line:

```text
uci
isready
setoption name AlphaBeta value true
setoption name IterativeDeepening value true
setoption name MoveOrdering value true
position startpos moves e2e4 e7e5
go depth 3
```

Commands: `uci`, `isready`, `ucinewgame`, `setoption`, `position startpos`,
`position fen` (six fields, optionally followed by moves), `go`, `stop`, `quit`.
Options: `AlphaBeta`, `IterativeDeepening`, `MoveOrdering` (all default true), and `Depth`
(default 3, range 1–8). `go` accepts depth, movetime (milliseconds), nodes, and
infinite. Bare `go` uses the Depth option. Time/node-limited requests without an
explicit depth, and infinite searches, permit deepening through a safety cap of
64 plies until stopped. Clock allocation and pondering are not implemented.

The input thread remains responsive during worker searches. `info` reports depth,
selective depth, nodes, time, approximate NPS, score, and legal principal variation.
UCI scores favor the player to move; the GUI converts to White's perspective.
Terminal/no-move results use `bestmove 0000`.

Interrupted searches retain the most recent completed depth/score/PV. A final
metadata update reports total work without replacing those fields. When deepening
is disabled, an interrupted target pass has depth zero and no proven score. The GUI
uses a 15-second safety limit per algorithm, allows target depths 1–5, and labels
results as completed/target (for example, `3/5`) when the target was not reached.
It computes comparison reductions only when both searches reach the same target.
Unknown commands are ignored; invalid positions/moves report errors and leave
the previous position unchanged.

## GUI integration

Press G for opponent/color/algorithm/depth settings and E for Search lab. Compare
position runs both algorithms sequentially on one snapshot without playing either
move. It displays move, completed depth, nodes, time, score, and node reduction.
Completed passes stream live, with per-depth history for the latest algorithm.
**Stop** retains the completed result and stops remaining comparison work; reset
and Undo cancel and discard the request instead.
Play pauses while this panel is open.

`app/engine_client.py` communicates through python-chess in a background worker.
Jobs receive full-history board copies and revision/tokens. Only the GUI thread
applies validated replies through `Game.play` after the final response. Progress
messages update statistics only. Reset, Undo, mode changes, and
shutdown cancel subprocess work; stale replies are ignored. Errors leave the game
unchanged instead of triggering a retry loop.

## Verification

Build first, then run `.venv\Scripts\python.exe -m pytest -q` from the root.
Tests include perft (197,281 at initial depth 4; 97,862 at Kiwipete depth 3), legal
move cross-checks against python-chess, terminal states, search equivalence,
interruptible UCI, cancellation, and actual engine-to-GUI play/comparison.
The 218-test suite also checks optimal moves/scores against an independent Python
reference with ordering off/on, both algorithms, and direct/iterative search.

Original baseline with **MoveOrdering=false**, initial target depth 3
(all select a3 with White score 0.00):

| Algorithm | Deepening off | Deepening on |
| --- | ---: | ---: |
| Minimax | 9,323 nodes | 9,765 nodes |
| Alpha-beta | 586 nodes | 667 nodes |

Measured iterative alpha-beta, same completed depth/evaluation in each pair:

| Position | Depth | Ordering off | Ordering on | Fewer nodes |
| --- | ---: | ---: | ---: | ---: |
| Initial | 5 | 38,388 | 25,261 | 34.2% |
| Kiwipete | 4 | 63,617 | 9,754 | 84.7% |

Both initial searches select b3 (+1.00); both Kiwipete searches select Bxa6
(+0.10). Kiwipete FEN:
`r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1`.
Reproduce with `AlphaBeta=true`, `IterativeDeepening=true`, the respective
`position` and `go depth` commands, toggling `MoveOrdering` between runs.

With a shared 50-node budget, iterative Minimax completes depth 1 before being
interrupted at depth 2. Direct depth-3 Minimax completes no pass and returns only
a fallback. A poisoned-pawn test where depths 1 and 2 disagree proves interruption
retains the exact earlier move, score, and PV.

Node counts measure work, not playing strength: material-only evaluation makes
many quiet moves equivalent.

Standalone rules diagnostics:

```powershell
.\engine\build\chesslab-engine.exe --perft 4
.\engine\build\chesslab-engine.exe --legal-moves "7k/P7/8/8/8/8/8/7K w - - 0 1"
```

## Third-party rules

Disservin's MIT-licensed C++ chess library version 0.9.4 is vendored at revision
`53e6a841dcda7059a2af363d85f785ef1817304a`. The original header/license are unchanged.
Its position hashes support repetition detection; ChessLab has no search cache.
