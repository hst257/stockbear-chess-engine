# ChessLab engine: search and configurable evaluation

A standalone C++17 UCI executable implements Minimax with optional alpha-beta
pruning, iterative deepening, move ordering, material/PST evaluation, and
Zobrist-based transposition caching, quiescence, Principal Variation Search, aspiration windows, null-move pruning, and LMR.
It owns its board independently of Python.
No search or evaluation is delegated to another engine.

Version 0.13 adds `Evaluator` (`classical` default, or `nnue`) and diagnostic
`NNUEIncremental` (true default). The compact StockBear float32 model is validated
and embedded during build. See the [NNUE guide](../docs/nnue.md) for the exact
feature/score contract, model identity, selection controls and match results.

Version 0.12 adds switchable history/killer ordering, legal-recapture SEE,
adaptive LMR, guarded forward/reverse futility, two-ply-budget check extensions,
bare-king conversion and MG/EG component weight tuning. See the
[strength upgrade guide](../docs/strength-upgrade.md) for switches, guards,
exhaustive baseline settings, experiments and reproduction commands.

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

Advanced classical evaluation now defaults to on. See the [complete component/weight guide](../docs/advanced-evaluation.md). `UseAdvancedEvaluation=false` restores the exact historical material/PST evaluator described below; disable `UsePST` too for material only. All historical benchmarks use advanced evaluation off.


`src/search.cpp` contains one recursive Minimax implementation. White maximizes
and Black minimizes the same White-relative score. Material values are unchanged:

| Piece | Centipawns |
| --- | ---: |
| Pawn | 100 |
| Knight | 320 |
| Bishop | 330 |
| Rook | 500 |
| Queen | 900 |
| King | 0 (handled through terminal detection) |

Each node generates legal moves, checks mate/stalemate, checks draws, then
enters quiescence at depth zero (or evaluates statically when disabled). Mate distance favors faster wins and slower
losses. Terminal detection precedes draw counters.

With `AlphaBeta=false`, no alpha/beta cutoffs are applied; exact table hits can
still reuse completed subtrees. With `AlphaBeta=true`, the same
function updates alpha/beta bounds and cuts branches that cannot affect the answer.
Both modes share the same ordering policy and first-best tie rule. PVS is active
only with alpha-beta. Minimax ignores aspiration/NMP/LMR; NMP/LMR are selective,
so equal nominal depth need not give the exhaustive score. Forward/reverse futility and bounded check extensions are also selective; disable them for exhaustive comparisons. History/killer ordering is implemented; opening books and neural networks remain deferred.

`src/evaluation.cpp` adds positional centipawns from the compile-time arrays in
`src/pst.hpp`, one table per piece plus a second king table. `UsePST=true`
(default) adds these to material; false removes PST contributions. With advanced evaluation also off, this restores the original material-only fast
path. Black mirrors ranks with `square ^ 56`; no file reversal is used. Phase
counts both sides' N/B=1, R=2, Q=4, clamped to 0–24. Each king blends its
middlegame/endgame entries by that phase, rounded to the nearest centipawn with
halves away from zero. Material is never included in the tables themselves.

Toggle **PST: on/off** in setup, use **PST: on/off**
in Search lab, or pass `--no-pst` to the Python launcher. Search lab's two
algorithms always use the same evaluation. See the [PST guide](../docs/pst.md) for
all tables/source notices, worked examples, tests, benchmarks, and limitations.

## Iterative deepening

Enabled by default, deepening searches depth 1, then 2, through the target depth.
Timed `go movetime MS` without an explicit depth forces iterative deepening up
to the 64-ply safety ceiling, even if IterativeDeepening is false. It can stop
early on terminal positions or a proven root mate. `go depth N` preserves the
selected iterative/direct policy.
Each completed pass commits its move, score, and principal variation together and
emits a UCI `info` update. A deeper unfinished pass cannot overwrite that snapshot.
Time and node limits cover all passes together, not a fresh budget for each pass.

On `stop` or a limit, the engine returns the last completed result. Depth reports
that completed depth, while final nodes/time include work spent on the interrupted
pass. Before depth 1 finishes, it returns an unscored legal fallback at depth 0.
Terminal positions are resolved directly without repeating identical passes.

Time mode shows **Deepening: automatic**. In fixed-depth mode, toggle
**Deepening: on/off** in setup or Search lab. CLI: `--search-mode depth --no-iterative-deepening` selects direct search. UCI: `setoption name IterativeDeepening value false`.
Both comparison algorithms share limits, deepening policy, and evaluation;
timed completed depths can differ.

With NMP/LMR disabled, completed full-depth scores match direct search. With ordering enabled, the
previous PV can change which equally good move is searched first. Its benefit
depends on the position; shallow passes still count toward the total work.

Depth counts nominal plies (half-moves); `seldepth` includes tactical extensions.
Nodes include root, interior, terminal, static leaves, quiescence calls, and PVS
re-searches across all passes, including repeated positions and unfinished work. Completed
pass history records cumulative totals at each checkpoint. Time uses a monotonic
clock in milliseconds; tiny searches can report zero.

Search treats currently claimable threefold/50-move positions as drawn. The GUI
automatically claims eligible draws on the engine's turn, including intended-move
claims, before requesting a move. It may claim even when a win could exist. Human
claims remain explicit.

## Deadline and cancellation safety

Each search records `steady_clock` start/deadline before allocating its table.
Stop and node limits are checked at every main/Q invocation; deadline checks
run every 256 nodes and before each iteration. A single interruption exception
unwinds main search, Q, and PVS re-searches. `ScopedMove` restores every temporary
move through RAII, including captures, castling, promotions, and en passant.
Incomplete nodes never reach TT storage; completed descendants remain valid.
The existing input thread signals an atomic stop and joins the one worker,
which emits exactly one bestmove. No overlapping search workers are started.
Timings include unfinished work; saved score/PV/depth stay together.

## Move ordering

Enabled by default in both algorithms. At each non-leaf node, stable sorting uses these priorities:

1. A matching transposition-table move, if available.
2. The previous completed iteration's PV move, only while following that PV's
   exact prefix. Siblings never reuse hints based only on their ply.
3. Promotions, prioritized by promoted-piece value and any capture bonus.
4. Captures using MVV-LVA: `10 × victim value − attacker value`.
5. Quiet moves in the original rules-library order.

The library identifies en passant's pawn victim and excludes castling from
captures. Capture promotions receive both bonuses. Equal priorities preserve
library order; the first equally scored searched move wins. Ordering can change
the selected move/PV among ties while preserving the full-depth minimax score.
It creates earlier alpha-beta cutoffs; with transposition caching disabled,
exhaustive Minimax visits the same nodes and pays sorting overhead. Node savings
and elapsed-time gains vary by position.

Setup offers **Ordering: on/off**. Search
lab's **Ordering: on/off** preserves the board and clears old rows; rerun Compare
position to measure the new setting. Toggles are disabled during searches. CLI:
`--no-move-ordering`. UCI: `setoption name MoveOrdering value false`. Disabling
ordering bypasses all sorting and PV hints, restoring the original traversal.
Hints are local to one search and come only from fully completed passes.

## Quiescence and Principal Variation Search

Both are enabled by default and independently switchable. Quiescence searches
captures (including en passant), every promotion, and all legal check evasions.
Non-check nodes use stand pat; checked nodes must search evasions. Terminal and
draw checks precede evaluation. Alpha-beta can cut Q branches; Minimax exhausts
the same tactical tree. Q leaves count once in total nodes and also in `qnodes`.

The soft Q limit is 16 extra plies. At non-check nodes, that or absolute ply 64
returns static evaluation and increments `qcaps`, even if captures remain.
Checks extend past the soft limit; an unresolved nonterminal check at ply 64
interrupts the iteration (`plylimit=1`), retaining the previous completed result.
Stop/time/node budgets apply throughout. Quiet checking moves and SEE/delta
pruning are not included; stand pat remains a zugzwang approximation.

PVS searches the first child with the full window. Later White moves use
`[alpha, alpha+1]`; Black moves use `[beta-1, beta]`. A result strictly inside
the original full window triggers a full-window re-search. Unit-width windows
use ordinary alpha-beta. Minimax never uses scouts. At fixed Q settings with NMP/LMR, forward/reverse futility and check extensions disabled, PVS
preserves full-window scores; tied moves may differ. Q itself changes the leaf model.

Setup and Search lab provide **Quiescence: on/off** and **PVS: on/off**; setup
marks PVS inactive for Minimax. Search lab compares Minimax against PVS or
Alpha-beta, using identical Q settings. CLI: `--no-quiescence`, `--no-pvs`.
See the [search guide](../docs/search.md) for comparisons and limitations.

## Aspiration, null move, and late reductions

`UseAspirationWindows`, `UseNullMovePruning`, and `UseLMR` default true.
Aspiration uses the previous completed score ±`AspirationDelta` (25 cp, 1–500),
doubling only a failed bound and retrying before publishing an exact pass.
NMP uses R=2 at guarded unit-window non-PV nodes. Synthetic branches skip normal
TT/repetition/50-move reuse; null-inferred mates never cut. LMR skips the first
four moves and tactical/TT/PV moves, reduces by `LMRReduction` (1, range 1–3,
clamped to leave ≥1 child ply), and verifies promising reductions at full depth.
Both selective techniques avoid wide PV nodes, checks, and sparse endgames;
LMR also requires ordering. Disabling PVS generally leaves them inactive.
`info string optim` and final summaries expose cumulative counters.

CLI switches: `--no-aspiration-windows`, `--no-null-move-pruning`, `--no-lmr`.
The [optimization guide](../docs/search-optimizations.md) records complete guards,
UCI examples, diagnostics, tests, independent stages, and controlled benchmarks.
For historical exhaustive comparisons also disable forward/reverse futility and check extensions; disable history/killers/SEE when reproducing old traversal order. Selective scores can
change with depth, ordering, cache, and window policy; an EXACT TT tag is relative
to the selected search policy, not a full-width guarantee.

## Transposition tables

Enabled by default, a bounded per-search table caches completed nodes across
iterative passes. The rules library already supplies incremental 64-bit Zobrist
keys; no duplicate position-hashing system or vendor changes were needed.
Full keys, halfmove clocks, and reversible-history fingerprints guard probes.
Exact/lower/upper bounds, equal-depth score reuse, and ply-normalized mate scores
preserve fixed-depth answers. With Q enabled, score reuse also requires the
same root ply to preserve extension allowances. Q nodes themselves are not
stored as main-depth entries; main entries include their completed Q result.
Compact complete PVs retain legal reported lines.

Each search starts fresh, preventing score reuse across different evaluation or
algorithm settings. Hash capacity defaults to a 16 MiB cap (rounded down to a
power-of-two slot count), configurable via UCI `Hash` from 1 to 256. Disabling
`TranspositionTable` bypasses the cache and its hints. Both GUI setup and Search
lab offer on/off controls; CLI: `--no-transposition-table`. Search lab displays
hits, cutoffs, and occupancy. The [TT guide](../docs/transposition-tables.md)
explains repetition context, replacement, interruption, memory, and benchmarks.

## UCI

Run the executable directly and enter one command per line:

```text
uci
isready
setoption name AlphaBeta value true
setoption name IterativeDeepening value true
setoption name MoveOrdering value true
setoption name UsePST value true
setoption name TranspositionTable value true
setoption name Quiescence value true
setoption name PVS value true
setoption name UseAspirationWindows value true
setoption name UseNullMovePruning value true
setoption name UseLMR value true
setoption name Hash value 16
position startpos moves e2e4 e7e5
go depth 3
```

Commands: `uci`, `isready`, `ucinewgame`, `setoption`, `position startpos`,
`position fen` (six fields, optionally followed by moves), `go`, `stop`, `quit`,
and the optional diagnostic `eval`.
Options: `UseAdvancedEvaluation`, `EvalPawns`, `EvalPassers`, `EvalBishopPair`, `EvalRooks`, `EvalMobility`, `EvalOutposts`, `EvalKingSafety`, `EvalSpace`, `EvalEndgame` (all checks default true), `AlphaBeta`, `IterativeDeepening`, `MoveOrdering`, `UsePST`,
`TranspositionTable`, `Quiescence`, `PVS`, `UseAspirationWindows`,
`UseNullMovePruning`, `UseLMR` (all default true), `Hash` (default 16 MiB cap, range 1–256),
`AspirationDelta` (default 25 cp, 1–500), `LMRReduction` (default 1, 1–3),
and `Depth` (default 3, range 1–8). `go` accepts depth, movetime (milliseconds), nodes, and
infinite. Bare `go` uses the Depth option. Time/node-limited requests without an
explicit depth, and infinite searches, permit deepening through a safety cap of
64 plies until stopped. Clock allocation and pondering are not implemented.

The input thread remains responsive during worker searches. `info` reports depth,
selective depth, nodes, time, approximate NPS, score, and legal principal variation.
`hashfull` is occupied table slots per thousand; `info string tt probes N hits H
cutoffs C` reports cache statistics. `info string search qnodes N scouts N
researches N qcaps N plylimit 0` reports Q/PVS counters; plylimit is 1 if the
absolute check ceiling stopped the pass. Final summary includes total counters.
UCI scores favor the player to move; the GUI converts to White's perspective.
Terminal/no-move results use `bestmove 0000`.

Interrupted searches retain the most recent completed depth/score/PV. A final
metadata update reports total work without replacing those fields. When deepening
is disabled, an interrupted target pass has depth zero and no proven score. The GUI
defaults to a 1000 ms time-only limit, with five presets from 100 to 5000 ms.
Fixed-depth mode retains a 15-second safety limit and targets 1–5, displaying
completed/target (for example, `3/5`) if interrupted. Only equal completed
fixed-depth comparisons show node reductions; timed algorithms may finish
different depths. See [time management](../docs/time-control.md).
Unknown commands are ignored; invalid positions/moves report errors and leave
the previous position unchanged.

`eval` stops current search and emits `info string eval {JSON}` with White-relative
material, six PST contributions, positional sum, total, and phase. No debug text
is printed during normal UCI searches. Standalone equivalent: `--eval [--no-pst] [--baseline] [--disable EvalCategory] FEN`. Advanced JSON adds raw MG/EG and tapered component scores, rounding and scaling adjustments, and the final total. `--eval-bench [flags] [--repeats COUNT] FEN` measures evaluation calls without process-start overhead.
Static diagnostics do not adjudicate terminal positions; search does so before
evaluating leaves. Both paths use the same evaluation implementation.

## GUI integration

Press G for opponent/color/algorithm/time settings and E for Search lab. Compare
position runs both algorithms sequentially on one snapshot without playing either
move. It displays move, completed depth, nodes, time, score, and node reduction.
Completed passes stream live, with per-depth history for the latest algorithm.
**Stop** retains the completed result and stops remaining comparison work; reset
and Undo cancel and discard the request instead.
Play pauses while this panel is open.

`app/engine_client.py` communicates through python-chess in a background worker.
Jobs receive immutable settings, full-history board copies, and revision/tokens.
Apply to game preserves the board; time changes affect subsequent requests,
leaving active budgets intact. Changing opponent/color cancels incompatible work. Only the GUI thread
applies validated replies through `Game.play` after the final response. Progress
messages update statistics only. Reset, Undo, mode changes, and
shutdown cancel subprocess work; stale replies are ignored. Errors leave the game
unchanged instead of triggering a retry loop.

## Verification

Build first, then run `.venv\Scripts\python.exe -m pytest -q` from the root.
Tests include perft (197,281 at initial depth 4; 97,862 at Kiwipete depth 3), legal
move cross-checks against python-chess, terminal states, search equivalence,
interruptible UCI, cancellation, and actual engine-to-GUI play/comparison.
The 929-test suite also checks optimal moves/scores against an independent Python
reference with ordering off/on, both algorithms, and direct/iterative search.
PST coverage includes all pieces, color/rank orientation, phase/rounding, diagnostic
and search consistency, unchanged terminal behavior, and GUI on/off selection.

Native TT unit tests are compiled automatically with the build helper. They cover
incremental/full hashes, special moves and unmake, key/context collisions, bounds,
depth validity, replacement, and mate-distance normalization. Integration tests
verify cached/uncached scores, complete legal PVs, exhaustive child values, draw
histories/clocks, interruption, and both GUI modes.

**Historical measurements below disable advanced evaluation, Q, PVS, aspiration, NMP, and LMR.**

Original baseline with **UseAdvancedEvaluation=false, TranspositionTable=false, UsePST=false, MoveOrdering=false**, initial target depth 3
(all select a3 with White score 0.00):

| Algorithm | Deepening off | Deepening on |
| --- | ---: | ---: |
| Minimax | 9,323 nodes | 9,765 nodes |
| Alpha-beta | 586 nodes | 667 nodes |

Measured iterative alpha-beta with **UseAdvancedEvaluation=false, TranspositionTable=false, UsePST=false**,
same completed depth/evaluation in each pair:

| Position | Depth | Ordering off | Ordering on | Fewer nodes |
| --- | ---: | ---: | ---: | ---: |
| Initial | 5 | 38,388 | 25,261 | 34.2% |
| Kiwipete | 4 | 63,617 | 9,754 | 84.7% |

Both initial searches select b3 (+1.00); both Kiwipete searches select Bxa6
(+0.10). Kiwipete FEN:
`r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1`.
Reproduce with `UseAdvancedEvaluation=false`, `TranspositionTable=false`, `UsePST=false`, `AlphaBeta=true`, `IterativeDeepening=true`, the respective
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
.\engine\build\chesslab-engine.exe --eval "7k/8/8/8/3N4/8/8/7K w - - 0 1"
```

Run matched evaluation benchmarks and optional color-balanced smoke games with
`python -m tools.benchmark_evaluation --match-games 4`. Recorded moves, scores,
nodes, time, NPS, raw JSON, and PGNs are in the [PST guide](../docs/pst.md#verification-and-benchmarks).
That benchmark explicitly disables TT, Q, and PVS to preserve the original comparison.
`python -m tools.benchmark_transpositions` compares the cache on/off with the same
PST evaluator and search settings. At initial depth 5, caching visits 118,406
instead of 182,596 nodes (35.2% fewer), returning the same e4 and +70 cp.
It explicitly disables Q/PVS. `python -m tools.benchmark_search` measures all
four Q/PVS combinations; [recorded results](../docs/search.md#measurements)
include FENs, legal PVs, counters, and three raw timing samples per mode.

## Third-party rules

Disservin's MIT-licensed C++ chess library version 0.9.4 is vendored at revision
`53e6a841dcda7059a2af363d85f785ef1817304a`. The original header/license are unchanged.
Its position hashes support repetition detection and ChessLab's own transposition
table; search, cache policy, and evaluation remain in `engine/src/`.

Numeric PST data is adapted from Andrew Healey's MIT-licensed Andoma implementation
of Tomasz Michniewski's classical tables. Full [notice and adaptation notes](vendor/andoma/README.md).


## Audited release 0.11

The [engine audit](../docs/engine-audit.md) and [performance report](../docs/performance-report.md)
cover reproducible baseline/paired measurements, exclusive instrumentation,
UBSan, full-state restoration, and original-versus-optimized games. Recursive
PVs and stable ordering no longer allocate. `PawnCache` and `FastMovegen` default
to true and preserve exact evaluation/search results; disable them independently
for ablations. Pawn keys verify both complete pawn bitboards; king/occupancy
terms stay live. Vendor sources are unchanged. Same-color promoted-bishop draws
are generalized outside the vendor. Imported clocks above 100 saturate under the
always-claim policy, avoiding the library's 8-bit counter overflow.

Portable O2 remains the default after paired O3/LTO measurements. Build variants
with `--optimization O3 --lto --output PATH`; `--profile` instruments exclusive
wall-time categories and search-thread new/new[] counts. `--target audit-tests
--sanitize undefined` checks randomized state/cache and bounded search behavior.
Every successful build writes a `.build.json` sidecar with exact flags. Set
`CHESSLAB_TEST_ENGINE` to select another binary for protocol/evaluation pytest
fixtures. Historical baseline `b5023bd` remains reproducible from Git; its original
executable is retained locally in `artifacts/audit/original-b5023bd.exe`.
